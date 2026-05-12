"""Shared player-link helpers.

Builds a player-name → profile URL map from the `players` table and rewrites
the first occurrence of each name in arbitrary markdown into a link. Used by
every daily Blot publisher (fantasy Daily Intel, Cardinals report, MLB
Roundup) so a single source of truth controls how player names are linked.

Prefers Baseball Savant when an mlbam_id is available, falls back to FanGraphs
when only a fangraphs_id is on file.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import unicodedata
from pathlib import Path

log = logging.getLogger(__name__)

PITCHING_POSITIONS = frozenset({"SP", "RP", "P"})

# Accent class groups — used to build patterns that match ASCII DB names
# ("Ivan Herrera") against accented prose ("Iván Herrera").
_ACCENT_GROUPS_LOWER = {
    "a": "aàáâãäåāăą",
    "e": "eèéêëēĕėęě",
    "i": "iìíîïīĭįı",
    "o": "oòóôõöøōŏő",
    "u": "uùúûüūŭůűų",
    "n": "nñń",
    "c": "cç",
    "y": "yýÿ",
}
_ACCENT_GROUPS_UPPER = {
    "A": "AÀÁÂÃÄÅĀĂĄ",
    "E": "EÈÉÊËĒĔĖĘĚ",
    "I": "IÌÍÎÏĪĬĮ",
    "O": "OÒÓÔÕÖØŌŎŐ",
    "U": "UÙÚÛÜŪŬŮŰŲ",
    "N": "NÑŃ",
    "C": "CÇ",
    "Y": "YÝŸ",
}


def _accent_insensitive_pattern(name: str) -> str:
    """Build a regex matching `name` and any common accent variant of it."""
    parts: list[str] = []
    for ch in name:
        nfd = unicodedata.normalize("NFD", ch)
        base = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
        if base in _ACCENT_GROUPS_LOWER:
            parts.append(f"[{_ACCENT_GROUPS_LOWER[base]}]")
        elif base in _ACCENT_GROUPS_UPPER:
            parts.append(f"[{_ACCENT_GROUPS_UPPER[base]}]")
        else:
            parts.append(re.escape(ch))
    return "".join(parts)


def load_player_links(db_path: Path) -> dict[str, str]:
    """Build player name → profile URL map from the players table.

    Prefers Baseball Savant (when `mlbam_id` is set) and falls back to FanGraphs
    (when only `fangraphs_id` is set). Players missing both IDs are skipped.

    Rostered players win on duplicate names (e.g. Max Muncy LAD vs ATH) because
    `ORDER BY on_roster ASC` makes them the last write into the dict.
    """
    links: dict[str, str] = {}
    if not db_path.exists():
        return links
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT p.name, p.mlbam_id, p.fangraphs_id, p.position,
                   EXISTS (SELECT 1 FROM rosters r WHERE r.player_id = p.id) AS on_roster
            FROM players p
            WHERE (p.mlbam_id IS NOT NULL AND p.mlbam_id != '')
               OR (p.fangraphs_id IS NOT NULL AND p.fangraphs_id != '')
            ORDER BY on_roster ASC
            """
        )
        for row in cur:
            name = row["name"]
            positions = set((row["position"] or "").split(","))
            is_pitcher = bool(positions & PITCHING_POSITIONS)
            slug = name.lower().replace(" ", "-").replace(".", "").replace("'", "")
            mlbam = row["mlbam_id"]
            if mlbam:
                stat_qs = "statcast-r-pitching-mlb" if is_pitcher else "statcast-r-batting-mlb"
                links[name] = (
                    f"https://baseballsavant.mlb.com/savant-player/{slug}-{mlbam}?stats={stat_qs}"
                )
                continue
            fg_id = row["fangraphs_id"]
            if fg_id:
                stat_type = "pitching" if is_pitcher else "batting"
                links[name] = f"https://www.fangraphs.com/players/{slug}/{fg_id}/stats/{stat_type}"
        conn.close()
    except Exception as e:  # noqa: BLE001 — links are enhancement-only
        log.warning("Could not load player_links: %s", e)
    return links


def linkify_players(text: str, player_links: dict[str, str]) -> str:
    """Replace every occurrence of each player name with a profile-page link.

    Sorts longest names first so "Jordan Walker" wins over a bare "Walker".
    The negative lookbehind/lookahead skip text that is already inside a
    markdown link, so re-running the linker is idempotent and links nested
    inside an outer `[Jordan Walker](...)` label aren't double-wrapped. The
    pattern is accent-insensitive so the ASCII DB form matches accented prose;
    the link label preserves the accented form as it appeared in prose.
    """
    if not player_links:
        return text
    sorted_names = sorted(player_links.keys(), key=len, reverse=True)

    for name in sorted_names:
        url = player_links[name]
        variant = _accent_insensitive_pattern(name)
        # `(?<!\[)` skips the label of an existing [Name](url); `(?!\]\()` skips
        # the trailing edge of one. Together they make the substitution safe to
        # apply to text that already has some names linked.
        pattern = rf"(?<!\[)({variant})(?!\]\()"

        def _replace(m: re.Match, u: str = url) -> str:
            return f"[{m.group(1)}]({u})"

        text = re.sub(pattern, _replace, text)

    return text
