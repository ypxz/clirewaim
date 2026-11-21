"""One command to bring the dashboard up to date.

    python3 -m ultraanalyse.refresh                       # public record + rebuild
    python3 -m ultraanalyse.refresh --drive FOLDER_URL    # also pull our logs from Google Drive

The Drive folder is expected to hold a `var/` directory as the runner writes it (`cases/`,
`decisions/`, `ai_log/`, `run_logs/runner/`). Only files that are new, were replaced, or
belong to a Game whose run log is still incomplete are downloaded again. Needs `gdown`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultraanalyse import build, fetch, render

PRIVATE_DIR = build.ROOT / "data" / "private"
MANIFEST = PRIVATE_DIR / "drive_manifest.json"
SKIP_NAMES = {"runner.log"}
GAME_DONE = "event=game status=completed"


def _incomplete(path: Path) -> bool:
    """A run log uploaded while its Game was still being played."""
    return "run_logs" in path.parts and GAME_DONE not in path.read_text(
        encoding="utf-8", errors="replace"
    )


def sync_drive(url: str) -> int:
    import gdown

    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    listing = gdown.download_folder(
        url=url, output=str(PRIVATE_DIR), quiet=True, skip_download=True
    )
    known = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    downloaded = 0
    for entry in listing:
        target = Path(entry.local_path)
        key = str(target.relative_to(PRIVATE_DIR))
        if target.name in SKIP_NAMES:
            continue
        if target.exists() and known.get(key) == entry.id and not _incomplete(target):
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
    parser.add_argument("--var", type=Path, default=build.DEFAULT_VAR)
    parser.add_argument("--team", default=build.OUR_TEAM)
    args = parser.parse_args()

    if args.drive:
        print(f"Drive: {sync_drive(args.drive)} files downloaded")
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
