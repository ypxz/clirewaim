"""Read what our runner wrote: run logs, decision logs, model replies and Cases.

Everything here is private runtime state under a `var/` directory. Every reader returns
an empty result when its input is missing, so the dashboard still builds from the public
record alone.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ultraanalyse import topics

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_AFTER_ROW = re.compile(r"\|\|\s+(\d+)\s+\|\s+([\d.]+)\s+\|\s+([\d.]+)\s*$")
_POSTED = re.compile(r"Posted (\d+) Line Items for Game (\d+) \(sequence=(\d+)")
_FRAUD_ITEM = re.compile(r"event=fraud_item .*line_item=(\d+) fraud=True")
_FIELD = re.compile(r"^(sequence|time|source|reason|write|fraud_locks): (.*)$")
_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ (WARNING|ERROR) (.*)$")


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_run_log(var: Path, game_id: int) -> dict:
    """The posts of one Game in order, and the values standing after the last one that landed."""
    posts: list[dict] = []
    flagged: set[int] = set()
    warnings: list[str] = []
    for path in sorted((var / "run_logs" / "runner").glob(f"game_{game_id:03d}_*.log")):
        block: dict | None = None
        for raw in _ANSI.sub(
            "", path.read_text(encoding="utf-8", errors="replace")
        ).splitlines():
            line = raw.rstrip()
            if line.strip() == "POST UPDATE":
                block = {"values": {}, "landed": False, "locks": []}
                posts.append(block)
                continue
            found = _FRAUD_ITEM.search(line)
            if found:
                flagged.add(int(found.group(1)))
            stamp = _STAMP.match(line)
            if stamp and stamp.group(3).strip():
                warnings.append(f"{stamp.group(2)}: {stamp.group(3).strip()[:200]}")
            if block is None:
                continue
            field = _FIELD.match(line)
            if field:
                key, value = field.groups()
                if key == "sequence":
                    block["sequence"] = int(value)
                elif key == "time":
                    block["at"] = float(re.search(r"T\+([\d.]+)s", value).group(1))
                elif key == "fraud_locks":
                    block["locks"] = [
                        int(n) for n in re.findall(r"\d+", value.split("]")[0])
                    ]
                else:
                    block[key] = value
                continue
            row = _AFTER_ROW.search(line)
            if row:
                block["values"][int(row.group(1))] = (
                    float(row.group(2)),
                    float(row.group(3)),
                )
                continue
            posted = _POSTED.search(line)
            if posted and block.get("sequence") == int(posted.group(3)):
                block["landed"] = True
    landed = [p for p in posts if p["landed"]]
    final = landed[-1] if landed else None
    return {
        "posts": [
            {
                "sequence": p.get("sequence"),
                "at": p.get("at"),
                "source": p.get("source"),
                "reason": p.get("reason"),
                "items": len(p["values"]),
                "landed": p["landed"],
            }
            for p in posts
        ],
        "final": final["values"] if final else {},
        "final_source": final.get("source") if final else None,
        "final_at": final.get("at") if final else None,
        "locks": sorted({n for p in landed for n in p["locks"]}),
        "flagged": sorted(flagged),
        "warnings": warnings[:8],
    }


def read_decision(var: Path, game_id: int) -> dict:
    """Strategy 2's decision log: the evidence behind each number."""
    data = _load_json(var / "decisions" / f"game_{game_id:03d}.json")
    if not data:
        return {}
    return {
        "winner": data.get("winner") or data.get("strategy"),
        "model_draws": data.get("model_draws"),
        "proposals": data.get("proposals") or {},
        "items": {int(item["index"]): item for item in data.get("items", [])},
    }


def read_model_replies(var: Path, game_id: int) -> dict:
    """Every model draw of one Game, and per Line Item what each draw said."""
    draws: list[dict] = []
    per_item: dict[int, list[dict]] = {}
    for path in sorted((var / "ai_log").glob(f"game_{game_id:03d}_*.json")):
        data = _load_json(path)
        if not data:
            continue
        draws.append(
            {
                "draw": data.get("draw"),
                "model": data.get("model"),
                "seconds": data.get("elapsed_seconds"),
                "at": data.get("recorded_at"),
            }
        )
        try:
            reply = json.loads(data.get("reply") or "{}")
        except ValueError:
            continue
        for item in reply.get("items", []) if isinstance(reply, dict) else []:
            try:
                index = int(item.get("line_item"))
            except (TypeError, ValueError):
                continue
            per_item.setdefault(index, []).append(
                {
                    "draw": data.get("draw"),
                    "coverage": item.get("coverage_probability"),
                    "low": item.get("price_low"),
                    "median": item.get("price_median"),
                    "high": item.get("price_high"),
                    "clause": (item.get("clause") or "").strip(),
                }
            )
    draws.sort(key=lambda d: d["at"] or 0)
    return {"draws": draws, "items": per_item}


def read_case(var: Path, game_id: int) -> dict:
    """The Case text. Game N plays Case N."""
    folder = var / "cases" / f"case_{game_id:02d}"
    try:
        description = (folder / "description.txt").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return {}
    try:
        policy = (folder / "policy.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        policy = ""
    return {
        "topic": topics.case_topic(description),
        "summary": topics.summary(description),
        "description": description.strip(),
        "policy": topics.policy_title(policy),
        "photos": sum(
            1 for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")
        ),
    }
