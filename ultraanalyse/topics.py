"""Keyword labels for a Case and for a Line Item. Rules, not a model: every label can be
traced to a word in the Case, and the same Case always gets the same label."""

from __future__ import annotations

import re

PERILS: list[tuple[str, tuple[str, ...]]] = [
    ("Power surge", ("surge", "lightning")),
    (
        "Burglary",
        ("burglar", "break-in", "intruder", "forced the back door", "was forced"),
    ),
    ("Robbery", ("robbery", "robbed", "mugg", "threatened with", "weapon")),
    ("Bicycle theft", ("bicycle was stolen", "bike was stolen", "stolen bicycle")),
    ("Theft", ("stolen", "theft")),
    ("Flood / heavy rain", ("flood", "rainfall", "inundation", "surface water")),
    ("Frost", ("frost", "freeze", "cold snap", "cold temperatures")),
    (
        "Water leak",
        ("escape of water", "leak", "pipe", "hose", "water damage", "dripping"),
    ),
    (
        "Accidental damage: electronics",
        ("laptop", " mac ", "phone", "tablet", "portable electronics"),
    ),
    ("Storm", ("storm", "hail")),
    ("Fire / smoke", ("fire", "smoke", "soot", "burn")),
    (
        "Accidental damage: contents",
        ("accidental damage", "knocked", "dropped", "cracked"),
    ),
]

ITEM_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    (
        "Upgrade / elective",
        ("upgrade", "elective", "premium", "optional", "pre-existing"),
    ),
    ("Travel / vehicle", ("vehicle cost", "travel", "call-out", "mileage", "journey")),
    ("Disposal", ("disposal", "removal of", "skip", "waste")),
    (
        "Diagnostics / report",
        ("diagnos", "inspection", "report", "assessment", "leak detection", "thermal"),
    ),
    ("Shipping / delivery", ("shipping", "delivery", "freight", "postage")),
    (
        "Drying / cleaning",
        ("drying", "dehumid", "cleaning", "disinfect", "extraction", "electricity"),
    ),
    (
        "Labour",
        (
            "hours",
            "labour",
            "labor",
            " hrs",
            "technician",
            "installer",
            "apprentice",
            "worker",
            "locksmith",
            "electrician",
            "plumber",
        ),
    ),
    (
        "Compensation / valuables",
        ("compensation", "jewel", "cash", "valuables", "watch", "stolen household"),
    ),
    (
        "Electronics / appliance",
        (
            "laptop",
            "screen",
            "speaker",
            "tv",
            "television",
            "receiver",
            "air conditioning",
            "boiler",
            "pump",
            "remote",
            "washing machine",
        ),
    ),
    (
        "Materials / building work",
        (
            "pipe",
            "plaster",
            "tile",
            "paint",
            "priming",
            "glass",
            "timber",
            "roof",
            "fitting",
            "insulation",
            "drilling",
            "frame",
            "material",
            "door",
            "lock",
        ),
    ),
    (
        "Flat rate / miscellaneous",
        ("flat rate", "miscellaneous", "sundries", "small parts"),
    ),
]

_SEPARATOR = re.compile(r"^[=\-\s]*$")


def _first_match(
    text: str, rules: list[tuple[str, tuple[str, ...]]], default: str
) -> str:
    lowered = f" {text.lower()} "
    for label, words in rules:
        if any(word in lowered for word in words):
            return label
    return default


def case_topic(description: str) -> str:
    """The peril. The opening of the description outranks the rest, where the bait lives."""
    opening = description[:400]
    return _first_match(opening, PERILS, "") or _first_match(
        description, PERILS, "Other"
    )


def item_category(name: str) -> str:
    return _first_match(name, ITEM_CATEGORIES, "Other")


def policy_title(policy: str) -> str:
    """Product line and edition from the policy header."""
    title, edition = "", ""
    for line in policy.splitlines()[:25]:
        stripped = line.strip()
        if (
            _SEPARATOR.match(stripped)
            or "mock document" in stripped.lower()
            or "no real contract" in stripped.lower()
        ):
            continue
        if not title and stripped.isupper() and "INSURANCE" in stripped:
            title = stripped.title()
        match = re.search(r"[\"”]\s*-\s*(.+?Edition)", stripped)
        if match:
            edition = match.group(1)
    return " - ".join(part for part in (title, edition) if part) or "Policy"


def summary(description: str, limit: int = 260) -> str:
    text = " ".join(description.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(". ", 1)[0]
    return (cut if len(cut) > 80 else text[:limit].rsplit(" ", 1)[0]) + "."
