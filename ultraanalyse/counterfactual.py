"""Replay our Limit and Charge under a different rule, holding every other team fixed.

    python3 -m ultraanalyse.counterfactual [--games 1-34]

Exact where the record is exact, bounded where it is not:

- Limit: every rival Charge that anyone paid is known, with whether it was fair. A rival
  Overcharge nobody accepted is unseen; it is assumed to stay rejected.
- Charge: a rival's Limit is an interval and the Fair Value a bracket, so income under a new
  Charge is reported as a pessimistic and an optimistic figure.

This is hindsight on the settled Games. A rule picked here is in-sample until it is checked
on Games it was not picked on; `--split` prints both halves for that reason.
"""

from __future__ import annotations

import argparse
import json

from ultraanalyse import build

COVERAGE_FLOOR = 2.0 / 3.0


def reviewer_cost(item: dict, us: str, limit: float) -> float:
    """What a Limit would have cost us on this Line Item."""
    cost = 0.0
    for name, rival in item["teams"].items():
        charge = rival["a"]
        if name == us or not charge:
            continue
        if rival["fair"] is False:
            # Paid at the Cap, the true Charge is unseen and at least 4t: no Limit rule here
            # reaches it, so it stays rejected.
            accepted = limit >= charge and rival["a_kind"] != "at-least"
            cost += charge if accepted else 0.0
        else:  # proven fair, or undetermined: counted as fair so a lower Limit is not flattered
            cost += charge if limit >= charge else 1.5 * charge
    return cost


def issuer_income(item: dict, us: str, charge: float) -> tuple[float, float]:
    """(pessimistic, optimistic) income of a Charge on this Line Item."""
    if charge <= 0:
        return 0.0, 0.0
    low = high = 0.0
    surely_fair = charge <= item["t_lo"]
    surely_over = item["t_hi"] is not None and charge >= item["t_hi"]
    for name, rival in item["teams"].items():
        if name == us:
            continue
        accepts = rival["b_lo"] >= charge
        rejects = rival["b_hi"] is not None and rival["b_hi"] <= charge
        paid_over = min(charge, item["cap"] or charge)
        fair_low, fair_high = (
            (charge, charge)
            if accepts
            else (1.5 * charge, 1.5 * charge)
            if rejects
            else (charge, 1.5 * charge)
        )
        over_low, over_high = (
            (paid_over, paid_over)
            if accepts
            else (0.0, 0.0)
            if rejects
            else (0.0, paid_over)
        )
        if surely_fair:
            low, high = low + fair_low, high + fair_high
        elif surely_over:
            low, high = low + over_low, high + over_high
        else:
            low, high = low + min(fair_low, over_low), high + max(fair_high, over_high)
    return low, high


def _items(dataset: dict, first: int, last: int) -> list[dict]:
    return [
        dict(item, game=game["id"])
        for game in dataset["games"]
        if first <= game["id"] <= last
        for item in game["items"]
        if item["logged"] and item["t_hat"]
    ]


def limit_rules() -> dict:
    rules = {"as played": lambda i: i["b"]}
    for k in (0.5, 0.75, 1.25, 1.5, 2.0, 3.0):
        rules[f"Limit x {k}"] = lambda i, k=k: i["b"] * k
    for k in (0.45, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25):
        rules[f"{k} x estimate where priced covered"] = lambda i, k=k: (
            k * i["t_hat"] if i["b"] > 0 else 0.0
        )
    for k in (0.3, 0.5, 0.7):
        rules[f"as played, but {k} x estimate where priced uncovered"] = lambda i, k=k: (
            i["b"] if i["b"] > 0 or i["fraud_lock"] else k * i["t_hat"]
        )
    return rules


def charge_rules() -> dict:
    rules = {"as played": lambda i: i["a"]}
    for k in (0.6, 0.7, 0.8, 0.9, 1.1, 1.2):
        rules[f"Charge x {k}"] = lambda i, k=k: i["a"] * k
    for k in (0.5, 0.6, 0.7, 0.8, 0.9):
        rules[f"{k} x estimate"] = lambda i, k=k: k * i["t_hat"]
    return rules


def report(items: list[dict], us: str, label: str) -> None:
    print(f"\n== {label}: {len(items)} Line Items")
    if not items:
        return
    base = sum(reviewer_cost(i, us, i["b"]) for i in items)
    actual = sum(i["cost"] for i in items)
    print(f"Reviewer cost as played: replay {base:,.0f}, record {actual:,.0f}")
    for name, rule in limit_rules().items():
        cost = sum(reviewer_cost(i, us, rule(i)) for i in items)
        print(f"  {name:55s} cost {cost:10,.0f}  saves {base - cost:+10,.0f}")
    low0, high0 = map(sum, zip(*(issuer_income(i, us, i["a"]) for i in items)))
    print(
        f"Issuer income as played: replay {low0:,.0f}..{high0:,.0f}, record {sum(i['income'] for i in items):,.0f}"
    )
    for name, rule in charge_rules().items():
        low, high = map(sum, zip(*(issuer_income(i, us, rule(i)) for i in items)))
        print(
            f"  {name:55s} income {low:10,.0f}..{high:10,.0f}  gain {low - low0:+10,.0f}..{high - high0:+10,.0f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", default="1-999", help="range of Games, e.g. 1-34")
    parser.add_argument(
        "--split", action="store_true", help="also print odd and even Games separately"
    )
    parser.add_argument("--team", default=build.OUR_TEAM)
    args = parser.parse_args()
    first, last = (int(part) for part in args.games.split("-"))
    items = _items(json.loads(build.DATASET.read_text()), first, last)
    report(items, args.team, f"Games {first}-{last}")
    if args.split:
        report([i for i in items if i["game"] % 2], args.team, "odd Games")
        report([i for i in items if not i["game"] % 2], args.team, "even Games")
        report(
            [i for i in items if "B:memory" in i["channels"]],
            args.team,
            "with Price Memory",
        )
        report(
            [i for i in items if "B:memory" not in i["channels"]],
            args.team,
            "model alone",
        )


if __name__ == "__main__":
    main()
