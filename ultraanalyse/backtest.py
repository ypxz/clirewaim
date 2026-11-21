"""Score a replayed run against the settled Transactions.

Every rival's Charge and Limit in a settled Game is fixed, so a different submission of ours
on the same Case has a net that can be computed after the fact. Replay the Cases through the
pipeline without posting, in a second copy of the repo so the live runner's `var/` is not
overwritten:

    python main.py --retry-dry 2>&1 | tee var/runner.log

then point this at that copy's `var/`:

    python -m ultraanalyse.backtest --var /path/to/copy/var

Two limits. A Charge above the recovered Fair Value bracket's lower end may or may not have
been fair, and an Overcharge paid at the Cap hides the rival's Charge; both give a range, and
a result is only a gain when the whole range is. And a replay is one more model read of the
same Case: run the unchanged pipeline first to see how much two runs differ by themselves.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultraanalyse import build, logs
from ultraanalyse.counterfactual import issuer_income, reviewer_cost


def score_game(
    game: dict, us: str, final: dict[int, tuple[float, float]]
) -> dict | None:
    """Net range of `final` on one Game, next to the net of what was played.

    Only Line Items present in both the replay and our logged submission are scored, so the
    two nets are over the same items.
    """
    low = high = played = 0.0
    scored = 0
    for item in game["items"]:
        ours = final.get(item["index"])
        if ours is None or not item["logged"]:
            continue
        charge, limit = ours
        income_low, income_high = issuer_income(item, us, charge)
        cost_low, cost_high = reviewer_cost(item, us, limit)
        low += income_low - cost_high
        high += income_high - cost_low
        played += item["net"]
        scored += 1
    if not scored:
        return None
    return {
        "game": game["id"],
        "items": scored,
        "low": low,
        "high": high,
        "played": played,
    }


def score_run(dataset: dict, var: Path) -> list[dict]:
    rows = []
    for game in dataset["games"]:
        final = {
            int(index): (float(pair[0]), float(pair[1]))
            for index, pair in logs.read_run_log(var, game["id"])["final"].items()
        }
        row = score_game(game, dataset["us"], final)
        if row:
            rows.append(row)
    return rows


def report(rows: list[dict], label: str) -> None:
    low, high, played = (sum(r[key] for r in rows) for key in ("low", "high", "played"))
    print(
        f"{label:12s} {len(rows):3d} Games  replay {low:11,.0f}..{high:11,.0f}"
        f"  played {played:11,.0f}  change {low - played:+11,.0f}..{high - played:+11,.0f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--var", type=Path, required=True, help="var/ directory of the replay"
    )
    parser.add_argument("--per-game", action="store_true", help="also print every Game")
    args = parser.parse_args()
    rows = score_run(json.loads(build.DATASET.read_text()), args.var)
    if not rows:
        print(f"No replayed Game found in {args.var}.")
        return
    if args.per_game:
        for row in rows:
            report([row], f"Game {row['game']}")
    report(rows, "all")
    report([r for r in rows if r["game"] % 2], "odd Games")
    report([r for r in rows if not r["game"] % 2], "even Games")


if __name__ == "__main__":
    main()
