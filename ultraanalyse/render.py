"""Turn data/dataset.json into one self-contained HTML file: out/dashboard.html.

    python3 -m ultraanalyse.render

No server, no network, no dependencies: the data is embedded and the charts are inline SVG.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "data" / "dataset.json"
TEMPLATE = ROOT / "template.html"
OUTPUT = ROOT / "out" / "dashboard.html"
PLACEHOLDER = "/*DATASET*/null"


def render(dataset: dict) -> str:
    payload = json.dumps(dataset, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace(PLACEHOLDER, payload)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        render(json.loads(DATASET.read_text(encoding="utf-8"))), encoding="utf-8"
    )
    print(f"dashboard -> {OUTPUT} ({OUTPUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
