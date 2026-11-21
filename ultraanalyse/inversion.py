"""Recover what every team did on one Line Item from the public Transactions.

A Transaction row is `{issuer, reviewer, line_item_index, accepted, amount}` and `amount` is
the money that moved from the Reviewer to the Issuer. Checked against the published income
and costs of all twelve teams, to the cent:

    accepted                 amount = min(a, c)     (a itself whenever a is fair)
    rejected, amount > 0     amount = 1.5 * a       the Charge was fair (a <= t)
    rejected, amount = 0     the Charge was an Overcharge (a > t)

So one wrongful rejection reveals the Issuer's Charge exactly and proves it fair, and one
free rejection proves an Overcharge. Limits are only ever seen as an interval: a Reviewer
accepted everything at or below its Limit and rejected everything above it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median

PENALTY_FACTOR = 1.5
TIGHT_BRACKET = 1.25
CAP_WITNESSES = 3


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def invert_item(
    rows: list[dict], known: dict[str, tuple[float, float]] | None = None
) -> dict:
    """Charges, Limit intervals, the Fair Value bracket and each team's money on one Line Item.

    `known` holds Charges and Limits we know exactly (our own, from the run log), keyed by team.
    """
    known = known or {}
    issued: dict[str, list[dict]] = defaultdict(list)
    reviewed: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        issued[row["issuer"]].append(row)
        reviewed[row["reviewer"]].append(row)
    teams = sorted(set(issued) | set(reviewed))

    charge: dict[str, dict] = {}
    for team in teams:
        mine = issued.get(team, [])
        paid_rejections = [
            r["amount"] for r in mine if not r["accepted"] and r["amount"] > 0
        ]
        free_rejections = [r for r in mine if not r["accepted"] and r["amount"] == 0]
        accepted = [r["amount"] for r in mine if r["accepted"]]
        if paid_rejections:
            entry = {
                "a": paid_rejections[0] / PENALTY_FACTOR,
                "kind": "exact",
                "fair": True,
            }
        elif free_rejections:
            paid = max(accepted, default=0.0)
            entry = {
                "a": paid or None,
                "kind": "exact" if paid else "unknown",
                "fair": False,
            }
        elif accepted and max(accepted) > 0:
            entry = {"a": max(accepted), "kind": "exact", "fair": None}
        else:
            entry = {"a": 0.0, "kind": "zero", "fair": True}
        if team in known:
            entry["a"], entry["kind"] = known[team][0], "logged"
        charge[team] = entry

    # Fair Value bracket: the largest Charge proven fair <= t < the smallest proven Overcharge.
    fair = [c["a"] for c in charge.values() if c["fair"] and c["a"]]
    over = [c["a"] for c in charge.values() if c["fair"] is False and c["a"]]
    t_lo = max(fair, default=0.0)
    t_hi = min(over, default=None)

    # The Cap shows itself when Overchargers are all paid the same amount. Two teams can pick
    # the same round Charge by chance, so it takes CAP_WITNESSES of them, and nobody may have
    # been paid more on this Line Item: the Cap is the most any accepted Charge can pay.
    capped = Counter(
        round(amount, 2)
        for team, mine in issued.items()
        if charge[team]["fair"] is False
        for amount in {r["amount"] for r in mine if r["accepted"] and r["amount"] > 0}
    )
    most_paid = max((r["amount"] for r in rows if r["accepted"]), default=0.0)
    cap = next(
        (
            amount
            for amount, n in capped.most_common(1)
            if n >= CAP_WITNESSES and amount >= most_paid - 0.01
        ),
        None,
    )
    for team, (logged_charge, _) in known.items():
        paid = max(
            (r["amount"] for r in issued.get(team, []) if r["accepted"]), default=0.0
        )
        if 0 < paid < logged_charge - 0.01:
            cap = paid
    if cap is not None:
        for entry in charge.values():
            if (
                entry["fair"] is False
                and entry["kind"] == "exact"
                and abs(entry["a"] - cap) < 0.01
            ):
                entry["kind"] = "at-least"
        # Only Charges below the Cap are exact Overcharges; the Cap itself bounds t at c / 4.
        exact_over = [
            c["a"]
            for c in charge.values()
            if c["fair"] is False and c["kind"] in ("exact", "logged")
        ]
        t_hi = (
            min(exact_over + [cap / 4.0])
            if t_lo <= cap / 4.0
            else min(exact_over, default=None)
        )

    for entry in charge.values():
        if entry["fair"] is None and entry["a"]:
            if entry["a"] <= t_lo:
                entry["fair"] = True
            elif t_hi is not None and entry["a"] >= t_hi:
                entry["fair"] = False

    limit: dict[str, dict] = {}
    for team in teams:
        b_lo, b_hi = 0.0, None
        for row in reviewed.get(team, []):
            seen = charge[row["issuer"]]
            if seen["a"] is None or seen["kind"] == "at-least" and not row["accepted"]:
                continue
            if row["accepted"]:
                b_lo = max(b_lo, seen["a"])
            else:
                b_hi = seen["a"] if b_hi is None else min(b_hi, seen["a"])
        entry = {"b_lo": b_lo, "b_hi": b_hi, "b": None}
        if team in known:
            entry["b"] = known[team][1]
        limit[team] = entry

    if t_lo > 0 and t_hi is not None:
        quality = "tight" if t_hi / t_lo <= TIGHT_BRACKET else "bounded"
    elif t_lo > 0:
        quality = "lower-bound"
    else:
        quality = "no-fair-charge"

    result_teams = {}
    for team in teams:
        income = sum(r["amount"] for r in issued.get(team, []))
        cost = sum(r["amount"] for r in reviewed.get(team, []))
        wrongful = [
            r["amount"]
            for r in reviewed.get(team, [])
            if not r["accepted"] and r["amount"] > 0
        ]
        overpaid = [
            r["amount"]
            for r in reviewed.get(team, [])
            if r["accepted"]
            and r["amount"] > 0
            and charge[r["issuer"]]["fair"] is False
        ]
        fair_paid = [
            r["amount"]
            for r in reviewed.get(team, [])
            if r["accepted"] and r["amount"] > 0 and charge[r["issuer"]]["fair"] is True
        ]
        # Accepted by every Reviewer and above every Charge proven fair: the record cannot say.
        unclear_paid = [
            r["amount"]
            for r in reviewed.get(team, [])
            if r["accepted"] and r["amount"] > 0 and charge[r["issuer"]]["fair"] is None
        ]
        rejected_income = [
            r["amount"]
            for r in issued.get(team, [])
            if not r["accepted"] and r["amount"] > 0
        ]
        result_teams[team] = {
            "rejected_income_n": len(rejected_income),
            "rejected_income": _round(sum(rejected_income)),
            "a": _round(charge[team]["a"]),
            "a_kind": charge[team]["kind"],
            "fair": charge[team]["fair"],
            "b": _round(limit[team]["b"]),
            "b_lo": _round(limit[team]["b_lo"]),
            "b_hi": _round(limit[team]["b_hi"]),
            "income": _round(income),
            "paid_by": sum(1 for r in issued.get(team, []) if r["amount"] > 0),
            "cost": _round(cost),
            "net": _round(income - cost),
            "wrongful_n": len(wrongful),
            "wrongful_cost": _round(sum(wrongful)),
            "penalty": _round(sum(wrongful) / 3.0),
            "overpaid_n": len(overpaid),
            "overpaid_cost": _round(sum(overpaid)),
            "fair_paid_n": len(fair_paid),
            "fair_paid_cost": _round(sum(fair_paid)),
            "unclear_paid_n": len(unclear_paid),
            "unclear_paid_cost": _round(sum(unclear_paid)),
        }

    return {
        "t_lo": _round(t_lo),
        "t_hi": _round(t_hi),
        "t_quality": quality,
        "cap": _round(cap),
        "n_issuers": sum(1 for c in charge.values() if c["a"] is None or c["a"] > 0),
        "n_fair": sum(1 for c in charge.values() if c["fair"] and c["a"]),
        "n_over": sum(1 for c in charge.values() if c["fair"] is False),
        "teams": result_teams,
    }


def fair_value_point(t_lo: float, t_hi: float | None) -> float:
    """One working number for the Fair Value: the bracket's geometric middle when it is
    tight, otherwise the largest Charge proven fair (a lower bound)."""
    if t_lo > 0 and t_hi is not None and t_hi / t_lo <= TIGHT_BRACKET:
        return round((t_lo * t_hi) ** 0.5, 2)
    return t_lo


def hindsight(item: dict, us: str) -> dict:
    """What the same Line Item would have paid us with perfect knowledge of t, holding
    every other team's Charge and Limit fixed.

    Reviewer: a Limit of exactly t accepts every fair Charge and rejects every Overcharge.
    Issuer: a Charge of t_lo, the largest Charge the record proves fair. That is a floor on
    the best Charge, so the Issuer gap is conservative.
    """
    teams = item["teams"]
    mine = teams[us]
    reviewer_regret = mine["penalty"] + mine["overpaid_cost"]
    best = item["t_lo"]
    benchmark = 0.0
    if best > 0:
        for name, other in teams.items():
            if name == us:
                continue
            rejects = other["b_hi"] is not None and other["b_hi"] <= best
            benchmark += best * (PENALTY_FACTOR if rejects else 1.0)
    return {
        "issuer_benchmark": round(benchmark, 2),
        "issuer_gap": round(max(benchmark - mine["income"], 0.0), 2),
        "issuer_bonus": round(max(mine["income"] - benchmark, 0.0), 2),
        "reviewer_regret": round(reviewer_regret, 2),
    }


def team_charge_ratio(observations: list[float], default: float = 0.7) -> float:
    """A team's typical Charge as a share of the Fair Value, on its fair Charges."""
    return round(median(observations), 3) if len(observations) >= 8 else default
