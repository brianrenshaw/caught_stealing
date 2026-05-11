"""Shared annotation helpers for Savant scoring_plays / key_swings entries.

Both the Cardinals digest and the MLB roundup feed these helpers their play
lists so the writer model has explicit `rbi` and `season_total` integers
on every play. Surfacing those numbers as structured fields removes the
need for the writer to count "X scores" mentions or parse parenthetical
totals from prose, which has historically been the most common fact-check
miss class ("solo homer" called "two-run", "doubled (7)" called "doubled
(8)", etc.).
"""

from __future__ import annotations

import re

# Savant play descriptions embed season totals like "Caminero homers (11)" or
# "Stott doubles (5)" or "Doe steals (4)". Capture the verb so the prompt can
# render natural phrasing ("his 11th homer", "his 5th double").
_SEASON_TOTAL_RE = re.compile(
    r"\b(homer|home run|double|triple|single|steal|stolen base)s?\s*\((\d+)\)",
    re.IGNORECASE,
)

# Map the regex verb to a clean noun for the prompt.
_VERB_TO_NOUN = {
    "homer": "HR",
    "home run": "HR",
    "double": "2B",
    "triple": "3B",
    "single": "1B",
    "steal": "SB",
    "stolen base": "SB",
}


def extract_season_total(description: str | None) -> dict | None:
    """Pull (verb, season_total) from a Savant play description.

    Returns None when the description has no parenthetical season count.
    Example input:  "Caminero homers (11) on a fly ball to left center..."
    Example output: {"event": "HR", "season_total": 11}
    """
    if not description:
        return None
    m = _SEASON_TOTAL_RE.search(description)
    if not m:
        return None
    verb = m.group(1).lower()
    try:
        n = int(m.group(2))
    except ValueError:
        return None
    return {"event": _VERB_TO_NOUN.get(verb, verb.upper()), "season_total": n}


def annotate_with_season_totals(plays: list[dict]) -> None:
    """In-place: attach `season_total` (int) + `season_event` (str) to plays.

    Only mutates entries where a parenthetical total is present in `description`.
    """
    for p in plays:
        info = extract_season_total(p.get("description"))
        if info:
            p["season_event"] = info["event"]
            p["season_total"] = info["season_total"]


def rbi_from_description(description: str | None, event: str | None) -> int | None:
    """Derive the play's RBI count from the Savant description string.

    Savant writes scorers as "<First Last> scores." after the lead clause:
        "Junior Caminero homers (11) on a fly ball to left center field."   → solo HR, 1 RBI
        "Player doubles (3) on a line drive. X scores. Y scores."           → 2 RBI
        "Player out on a sacrifice fly to LF. X scores."                    → 1 RBI (sac fly)

    Each occurrence of "<Name> scores" contributes 1 RBI. For a home run we add
    1 extra for the batter themselves (who scores on the HR but is not named
    in the "X scores" phrasing). Returns None when no description is present.
    """
    if not description:
        return None
    runners_scored = len(re.findall(
        r"\b[A-Z][\wÀ-ſ'’.]*"
        r"(?:\s[A-Z][\wÀ-ſ'’.]*)*"
        r"\s+scores\b",
        description,
    ))
    is_hr = bool(event and "home run" in event.lower())
    return runners_scored + (1 if is_hr else 0)


def annotate_with_rbi(plays: list[dict]) -> None:
    """In-place: attach `rbi` integer to each play.

    Calling this before sending data to the writer means the writer does not
    have to infer RBI counts from prose descriptions, historically the most
    common hallucination class ("solo homer" called "two-run").
    """
    for p in plays:
        rbi = rbi_from_description(p.get("description"), p.get("event"))
        if rbi is not None:
            p["rbi"] = rbi
