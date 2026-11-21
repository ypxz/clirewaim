"""Pull the public leaderboard record into ultraanalyse/data/raw/.

Only the endpoints the public leaderboard page calls, at a polite rate. Incremental:
a settled Game whose Transactions are already on disk is not fetched again.

    python3 ultraanalyse/fetch.py            # everything new
    python3 ultraanalyse/fetch.py --force    # re-pull every settled Game
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://c2f.public.quantco.cloud/leaderboard/api"
RAW_DIR = Path(__file__).resolve().parent / "data" / "raw"
SETTLE_GRACE_GAMES = 2
PAUSE_SECONDS = 0.15


def get(path: str) -> dict:
    with urllib.request.urlopen(API + path, timeout=30) as response:
        return json.load(response)


def get_all(path: str) -> list[dict]:
    """Every item of a paginated endpoint."""
    joiner = "&" if "?" in path else "?"
    items: list[dict] = []
    page = 1
    while True:
        data = get(f"{path}{joiner}page={page}&page_size=500")
        items.extend(data["items"])
        if page >= data.get("total_pages", 1):
            return items
        page += 1
        time.sleep(PAUSE_SECONDS)


def save(name: str, payload: object) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / name).write_text(json.dumps(payload), encoding="utf-8")


def game_transactions(game_id: int, teams: list[str]) -> list[dict]:
    """The endpoint needs a team filter, so ask for every team and deduplicate."""
    rows: dict[tuple, dict] = {}
    for team in teams:
        for row in get_all(
            f"/transactions?game_id={game_id}&team={urllib.parse.quote(team)}"
        ):
            rows[(row["issuer"], row["reviewer"], row["line_item_index"])] = {
                "issuer": row["issuer"],
                "reviewer": row["reviewer"],
                "line_item_index": int(row["line_item_index"]),
                "accepted": bool(row["accepted"]),
                "amount": float(row["amount"]),
            }
        time.sleep(PAUSE_SECONDS)
    return sorted(
        rows.values(), key=lambda r: (r["line_item_index"], r["issuer"], r["reviewer"])
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-pull Games already on disk"
    )
    args = parser.parse_args(argv)

    games = get_all("/games")
    save("games.json", games)
    matrix = get_all("/matrix")
    save("matrix.json", matrix)
    teams = [row["team_name"] for row in matrix]
    save(
        "performance.json",
        [get(f"/performance?team={urllib.parse.quote(t)}") for t in teams],
    )

    settled = [g["id"] for g in games if g.get("status") == "completed"]
    print(f"{len(teams)} teams, {len(settled)} settled Games of {len(games)}")
    for game_id in settled:
        name = f"transactions_game_{game_id:03d}.json"
        # The newest Games are pulled again: a Game can be listed before all its rows are.
        recent = game_id > max(settled) - SETTLE_GRACE_GAMES
        if (RAW_DIR / name).exists() and not args.force and not recent:
            continue
        rows = game_transactions(game_id, teams)
        save(name, rows)
        print(f"  Game {game_id}: {len(rows)} Transactions")


if __name__ == "__main__":
    main()
