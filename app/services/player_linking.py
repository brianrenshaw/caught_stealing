"""Shared player-link helpers.

Builds a player-name → profile URL map from the `players` table and rewrites
every occurrence of each name in arbitrary markdown into a link. Used by
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


# A markdown link's `(url)`, tolerating one level of nested parens (e.g. a
# `(disambiguation)` slug or a `?a=(b)` query param) so a `)` inside the URL
# doesn't truncate the match.
_URL_RE = r"\((?:[^()]|\([^()]*\))*\)"
_MD_LINK_RE = re.compile(r"\[([^\[\]]*)\]" + _URL_RE)


def linkify_players(text: str, player_links: dict[str, str]) -> str:
    """Replace every occurrence of each player name with a profile-page link.

    Sorts longest names first so "Jordan Walker" wins over a bare "Walker".
    Two safeguards prevent broken nested links:

    1. The (?<!\\[) / (?!\\]\\() lookarounds skip a name that is itself already
       wrapped as `[Name](url)`, so re-running the linker is idempotent.
    2. Each iteration recomputes the spans of existing `[label](url)` link
       labels and skips matches that fall *inside* one. Without this, a model-
       generated headline link like `[Maybe James Wood Just Thinks...](blog)`
       would have its inner "James Wood" wrapped into a malformed nested link
       (`[Maybe [James Wood](savant) Just Thinks...](blog)`).

    Accent-insensitive pattern so the ASCII DB form matches accented prose; the
    link label preserves the accented form as it appeared in prose.
    """
    if not player_links:
        return text
    sorted_names = sorted(player_links.keys(), key=len, reverse=True)

    # Spans of existing `[label](url)` link labels, recomputed only when a
    # substitution actually changes the text. Most dictionary names never
    # appear, so this avoids re-scanning the whole document on every one of the
    # ~thousands of entries.
    label_spans: list[tuple[int, int]] | None = None

    for name in sorted_names:
        url = player_links[name]
        variant = _accent_insensitive_pattern(name)
        pattern = rf"(?<!\[)({variant})(?!\]\()"

        if label_spans is None:
            label_spans = [(m.start(1), m.end(1)) for m in _MD_LINK_RE.finditer(text)]

        def _in_label(pos: int, spans: list[tuple[int, int]] = label_spans) -> bool:
            return any(start <= pos < end for start, end in spans)

        def _replace(m: re.Match, u: str = url) -> str:
            if _in_label(m.start()):
                return m.group(0)
            return f"[{m.group(1)}]({u})"

        new_text = re.sub(pattern, _replace, text)
        if new_text != text:
            text = new_text
            label_spans = None  # a new link was added; cached spans are stale

    return text


def unnest_broken_player_links(text: str) -> str:
    """Repair `[outer [inner](inner_url) outer](outer_url)` constructs created
    by the pre-fix linkify_players, collapsing each inner link down to its bare
    label text while leaving the enclosing outer link intact.

    Works by merging the leftmost link that sits inside another link's label
    into that label, then iterating until no nested links remain. Because each
    pass strips one inner link, an outer label holding any number of inner links
    (e.g. a headline naming two players) is fully flattened, and separate
    sibling links that are not nested are left untouched.
    """
    # `(\[[^\[\]]*)` is an open bracket plus non-bracket label text with no
    # close yet (an unclosed outer label); the following `\[...\](url)` is an
    # inner link nested inside it. Collapsing keeps the outer prefix and the
    # inner label, dropping the inner `](url)`.
    nested = re.compile(r"(\[[^\[\]]*)\[([^\[\]]*)\]" + _URL_RE)
    prev = None
    while prev != text:
        prev = text
        text = nested.sub(r"\1\2", text)
    return text


if __name__ == "__main__":  # one-time repair CLI for already-published markdown
    import sys

    # usage: uv run python -m app.services.player_linking <file.md> [<file.md> ...]
    targets = [Path(arg) for arg in sys.argv[1:]]
    if not targets:
        print(
            "usage: python -m app.services.player_linking <file.md> ...",
            file=sys.stderr,
        )
        raise SystemExit(2)
    for target in targets:
        original = target.read_text(encoding="utf-8")
        repaired = unnest_broken_player_links(original)
        if repaired != original:
            target.write_text(repaired, encoding="utf-8")
            print(f"repaired {target}")
        else:
            print(f"clean    {target}")
