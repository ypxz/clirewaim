"""One command to bring the dashboard up to date.

    python3 -m ultraanalyse.refresh                       # public record + rebuild
    python3 -m ultraanalyse.refresh --drive FOLDER_URL    # also pull our logs from Google Drive

The Drive folder is expected to hold a `var/` directory as the runner writes it (`cases/`,
`decisions/`, `ai_log/`, `run_logs/runner/`). Only files that are new, were replaced, or
belong to one of the last few Games are downloaded again; `--full` re-downloads everything
(use it after rewriting older logs in place). Needs `gdown`.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from ultraanalyse import build, fetch, render

PRIVATE_DIR = build.ROOT / "data" / "private"
MANIFEST = PRIVATE_DIR / "drive_manifest.json"
GROWING_NAMES = {"runner.log"}  # the supervisor appends to it for the whole tournament
GAME_DONE = "event=game status=completed"
RECENT_GAMES = 5
LAST_GAME = 1000
_GAME_NUMBER = re.compile(r"game_(\d+)")


def _incomplete(path: Path) -> bool:
    """A run log uploaded while its Game was still being played."""
    return "run_logs" in path.parts and GAME_DONE not in path.read_text(
        encoding="utf-8", errors="replace"
    )


def _game_of(key: str) -> int | None:
    found = _GAME_NUMBER.search(key)
    if not found or "cases" in Path(key).parts:
        return None
    game = int(found.group(1))
    return (
        game if game <= LAST_GAME else None
    )  # the test suite leaves a game_9042 behind


def sync_drive(url: str, full: bool = False) -> int:
    import gdown

    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    listing = gdown.download_folder(
        url=url, output=str(PRIVATE_DIR), quiet=True, skip_download=True
    )
    known = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    keys = {
        str(Path(entry.local_path).relative_to(PRIVATE_DIR)): entry for entry in listing
    }
    newest = max((game for game in map(_game_of, keys) if game is not None), default=0)
    downloaded = 0
    for key, entry in keys.items():
        target = PRIVATE_DIR / key
        # Drive keeps a file's id when it is overwritten in place, and logs of the Games just
        # played are still being written, so those are always fetched again.
        game = _game_of(key)
        recent = (
            target.name in GROWING_NAMES
            or game is not None
            and game > newest - RECENT_GAMES
        )
        current = (
            target.exists() and known.get(key) == entry.id and not _incomplete(target)
        )
        if current and not recent and not full:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            gdown.download(id=entry.id, output=str(target), quiet=True)
        except (
            OSError,
            gdown.exceptions.FileURLRetrievalError,
        ) as error:  # one unreadable file must not stop the refresh
            print(f"  could not download {key}: {error}")
            continue
        known[key] = entry.id
        downloaded += 1
    MANIFEST.write_text(json.dumps(known, indent=1), encoding="utf-8")
    return downloaded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--drive", help="Google Drive folder URL holding our var/ directory"
    )
    parser.add_argument(
        "--full", action="store_true", help="download every Drive file again"
    )
    parser.add_argument("--var", type=Path, default=build.DEFAULT_VAR)
    parser.add_argument("--team", default=build.OUR_TEAM)
    args = parser.parse_args()

    if args.drive:
        print(f"Drive: {sync_drive(args.drive, args.full)} files downloaded")
    fetch.main([])
    dataset = build.build(args.var, args.team)
    build.DATASET.write_text(json.dumps(dataset), encoding="utf-8")
    render.main()
    logged = [g["id"] for g in dataset["games"] if g["has_logs"]]
    missing = [g["id"] for g in dataset["games"] if not g["has_logs"]]
    print(
        f"{dataset['games_settled']} settled Games, our logs for {len(logged)}; missing logs: {missing or 'none'}"
    )


if __name__ == "__main__":
    main()
