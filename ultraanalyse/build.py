"""Join the public Transactions with our own logs into one dataset per Line Item.

    python3 -m ultraanalyse.build [--var PATH] [--team NAME]

Reads `ultraanalyse/data/raw/` (from fetch.py) and a private `var/` directory holding
`decisions/`, `ai_log/`, `run_logs/runner/` and `cases/`. Writes
`ultraanalyse/data/dataset.json`, which render.py turns into the dashboard.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from ultraanalyse import inversion, logs, topics

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
DATASET = ROOT / "data" / "dataset.json"
DEFAULT_VAR = ROOT / "data" / "private" / "var"
OUR_TEAM = "404"
COVERAGE_FLOOR = 2.0 / 3.0
FALLBACK_VALUES = (300.0, 35.0)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, 3)


def _tags(item: dict) -> list[str]:
    """Plain-language verdicts on one of our Line Items."""
    tags: list[str] = []
    covered = item["t_lo"] > 0
    said_covered = (
        item.get("coverage") is not None and item["coverage"] > COVERAGE_FLOOR
    )
    if item["fallback"]:
        tags.append("Fallback values submitted")
    if item["fraud_lock"]:
        tags.append("Fraud lock")
    if item.get("coverage") is not None:
        if covered and not said_covered:
            tags.append("Priced as uncovered, was covered")
        if not covered and said_covered and item["n_over"] >= 3:
            tags.append("Priced as covered, no fair Charge seen")
    if item["our_fair"] is False and covered:
        tags.append("Overcharged a covered item")
    if item["our_fair"] is False and not covered and item["income"] > 0:
        tags.append("Overcharge paid")
    if item["our_fair"] and covered and item["a"] < 0.6 * item["t_lo"]:
        tags.append("Undercharged")
    if item["wrongful_n"]:
        tags.append("Rejected fair claims")
    if item["overpaid_n"]:
        tags.append("Paid overcharges")
    ratio = item.get("estimate_ratio")
    if ratio is not None and item["t_quality"] in ("tight", "bounded"):
        if ratio > 1.5:
            tags.append("Estimate too high")
        elif ratio < 0.67:
            tags.append("Estimate too low")
    return tags


def build(var: Path, us: str) -> dict:
    games_meta = {g["id"]: g for g in json.loads((RAW_DIR / "games.json").read_text())}
    performance = json.loads((RAW_DIR / "performance.json").read_text())
    standings = sorted(performance, key=lambda p: -p["net"])
    teams = [p["team_name"] for p in standings]

    games: list[dict] = []
    ratios: dict[str, list[float]] = defaultdict(list)
    for path in sorted(RAW_DIR.glob("transactions_game_*.json")):
        game_id = int(path.stem.rsplit("_", 1)[1])
        rows = json.loads(path.read_text())
        by_item: dict[int, list[dict]] = defaultdict(list)
        for row in rows:
            by_item[row["line_item_index"]].append(row)

        run = logs.read_run_log(var, game_id)
        decision = logs.read_decision(var, game_id)
        replies = logs.read_model_replies(var, game_id)
        case = logs.read_case(var, game_id)

        items: list[dict] = []
        team_net: dict[str, float] = defaultdict(float)
        for index in sorted(by_item):
            # Only a post that landed is a submission. A recorded proposal is not: a fraud
            # lock can still rewrite its Limit, so without a run log the public record decides.
            submitted = run["final"].get(index)
            known = {us: submitted} if submitted else {}
            public = inversion.invert_item(by_item[index], known)
            if us not in public["teams"]:
                continue
            mine = public["teams"][us]
            evidence = decision.get("items", {}).get(index, {})
            t_point = inversion.fair_value_point(public["t_lo"], public["t_hi"])
            for name, entry in public["teams"].items():
                team_net[name] += entry["net"]
                if (
                    entry["fair"]
                    and entry["a"]
                    and public["t_quality"] in ("tight", "bounded")
                ):
                    ratios[name].append(entry["a"] / t_point)

            item = {
                "index": index,
                "name": " ".join(
                    (evidence.get("name") or f"Line Item {index}").split()
                ),
                "category": topics.item_category(evidence.get("name") or ""),
                "a": mine["a"],
                "b": mine["b"] if mine["b"] is not None else None,
                "b_lo": mine["b_lo"],
                "b_hi": mine["b_hi"],
                "logged": bool(submitted),
                "fallback": bool(submitted) and tuple(submitted) == FALLBACK_VALUES,
                "our_fair": mine["fair"],
                "t_hat": round(evidence["price_median"], 2)
                if evidence.get("price_median")
                else None,
                "t_hat_low": round(evidence["price_low"], 2)
                if evidence.get("price_low")
                else None,
                "t_hat_high": round(evidence["price_high"], 2)
                if evidence.get("price_high")
                else None,
                "sigma": round(evidence["sigma"], 3)
                if evidence.get("sigma") is not None
                else None,
                "coverage": evidence.get("coverage_probability"),
                "channels": evidence.get("channels") or [],
                "rule": evidence.get("rule"),
                "draws": replies["items"].get(index, []),
                "fraud_flag": index in run["flagged"],
                "fraud_lock": index in run["locks"],
                "t_lo": public["t_lo"],
                "t_hi": public["t_hi"],
                "t": t_point,
                "t_quality": public["t_quality"],
                "cap": public["cap"],
                "n_fair": public["n_fair"],
                "n_over": public["n_over"],
                "income": mine["income"],
                "paid_by": mine["paid_by"],
                "rejected_income_n": mine["rejected_income_n"],
                "rejected_income": mine["rejected_income"],
                "cost": mine["cost"],
                "net": mine["net"],
                "wrongful_n": mine["wrongful_n"],
                "wrongful_cost": mine["wrongful_cost"],
                "penalty": mine["penalty"],
                "overpaid_n": mine["overpaid_n"],
                "overpaid_cost": mine["overpaid_cost"],
                "fair_paid_n": mine["fair_paid_n"],
                "fair_paid_cost": mine["fair_paid_cost"],
                "unclear_paid_n": mine["unclear_paid_n"],
                "unclear_paid_cost": mine["unclear_paid_cost"],
                "teams": public["teams"],
            }
            item["a_ratio"] = _ratio(item["a"], t_point)
            item["b_ratio"] = _ratio(item["b"], t_point)
            item["estimate_ratio"] = _ratio(item["t_hat"], t_point)
            item.update(inversion.hindsight(public, us))
            item["tags"] = _tags(item)
            items.append(item)

        if not items:
            continue
        ranked = sorted(team_net.items(), key=lambda pair: -pair[1])
        meta = games_meta.get(game_id, {})
        games.append(
            {
                "id": game_id,
                "start": meta.get("start_time"),
                "topic": case.get("topic", "Unknown"),
                "summary": case.get("summary", ""),
                "description": case.get("description", ""),
                "policy": case.get("policy", ""),
                "photos": case.get("photos", 0),
                "has_logs": bool(run["final"]) or bool(decision),
                "posts": run["posts"],
                "final_source": run["final_source"],
                "final_at": run["final_at"],
                "warnings": run["warnings"],
                "model": next(
                    (d["model"] for d in replies["draws"] if d.get("model")), None
                ),
                "draws": replies["draws"],
                "n_teams": len(team_net),
                "team_net": {name: round(value, 2) for name, value in ranked},
                "rank": 1 + [name for name, _ in ranked].index(us),
                "best_team": ranked[0][0],
                "net": round(team_net[us], 2),
                "income": round(sum(i["income"] for i in items), 2),
                "cost": round(sum(i["cost"] for i in items), 2),
                "penalty": round(sum(i["penalty"] for i in items), 2),
                "overpaid": round(sum(i["overpaid_cost"] for i in items), 2),
                "issuer_gap": round(sum(i["issuer_gap"] for i in items), 2),
                "items": items,
            }
        )

    # A rival's estimate of t is never visible. Inferred as its Charge divided by the share
    # of the Fair Value it typically charges on Line Items where the bracket is closed.
    typical = {
        name: inversion.team_charge_ratio(values) for name, values in ratios.items()
    }
    for game in games:
        for item in game["items"]:
            for name, entry in item["teams"].items():
                entry["t_implied"] = (
                    round(entry["a"] / typical.get(name, 0.7), 2)
                    if entry["a"] and entry["a_kind"] != "at-least"
                    else None
                )

    profiles = []
    for row in standings:
        name = row["team_name"]
        entries = [
            (i, i["teams"][name])
            for g in games
            for i in g["items"]
            if name in i["teams"]
        ]
        covered = [(i, e) for i, e in entries if i["t_lo"] > 0]
        charged = [e for _, e in covered if e["a"] is None or e["a"] > 0]
        limits = [
            ((e["b_lo"] + e["b_hi"]) / 2 if e["b"] is None else e["b"]) / i["t"]
            for i, e in covered
            if e["b"] is not None or e["b_hi"] is not None
        ]
        fair_seen = sum(e["wrongful_n"] + e["fair_paid_n"] for _, e in entries)
        profiles.append(
            {
                "team": name,
                "net": round(row["net"], 2),
                "income": round(row["income"], 2),
                "costs": round(row["costs"], 2),
                "charge_ratio": typical.get(name),
                "charge_ratio_n": len(ratios.get(name, [])),
                "fair_share": _ratio(
                    sum(1 for e in charged if e["fair"]), len(charged)
                ),
                "silent_share": _ratio(
                    sum(1 for _, e in entries if e["a_kind"] == "zero"), len(entries)
                )
                or 0.0,
                "limit_ratio": round(median(limits), 3) if limits else None,
                "accept_fair_share": _ratio(
                    sum(e["fair_paid_n"] for _, e in entries), fair_seen
                ),
                "penalty": round(sum(e["penalty"] for _, e in entries), 2),
                "overpaid": round(sum(e["overpaid_cost"] for _, e in entries), 2),
            }
        )

    raw_rows = [
        r
        for p in sorted(RAW_DIR.glob("transactions_game_*.json"))
        for r in json.loads(p.read_text())
    ]
    versus = {
        name: round(
            sum(
                r["amount"]
                for r in raw_rows
                if r["issuer"] == us and r["reviewer"] == name
            )
            - sum(
                r["amount"]
                for r in raw_rows
                if r["issuer"] == name and r["reviewer"] == us
            ),
            2,
        )
        for name in teams
        if name != us
    }

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "us": us,
        "teams": teams,
        "games_scheduled": len(games_meta),
        "games_settled": len(games),
        "profiles": profiles,
        "versus": versus,
        "games": games,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--var",
        type=Path,
        default=DEFAULT_VAR,
        help="private var/ directory with our logs",
    )
    parser.add_argument(
        "--team", default=OUR_TEAM, help="our team name on the leaderboard"
    )
    args = parser.parse_args()
    dataset = build(args.var, args.team)
    DATASET.write_text(json.dumps(dataset), encoding="utf-8")
    logged = sum(1 for g in dataset["games"] if g["has_logs"])
    print(
        f"{dataset['games_settled']} settled Games, {logged} with our logs -> {DATASET}"
    )


if __name__ == "__main__":
    main()
