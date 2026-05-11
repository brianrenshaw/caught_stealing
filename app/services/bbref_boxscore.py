"""Scrape Baseball Reference box score pages for cross-reference data.

Used as a SECONDARY ground truth alongside the Savant gamefeed when fact-
checking generated roundup prose. bbref's play-by-play table has a clean
text `play_desc` for every plate appearance + signed WPA delta + the runs/
outs effect of the play. Comparing claims against both Savant and bbref
catches errors either source might have missed.

URL pattern (verified against May 2026 games):

    https://www.baseball-reference.com/boxes/{HOME_BBREF_CODE}/{HOME_BBREF_CODE}{YYYYMMDD}{N}.shtml

  - HOME_BBREF_CODE: 3-letter bbref team code (differs from MLB abbrev for
    several clubs — see BBREF_CODE_FROM_MLB_NAME below)
  - N: doubleheader index (0 single game, 1/2 for split-DH games)

bbref blocks bare user-agents; we send a desktop browser UA. Responses are
cached on disk for 24h via the project's diskcache so re-runs (debugging,
fact-check retries) don't re-hit bbref.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Any

import httpx

from app.cache import cache

log = logging.getLogger(__name__)

BBREF_BASE = "https://www.baseball-reference.com/boxes"
BBREF_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TTL_BBREF_HTML = 24 * 60 * 60  # 24h, box scores never change after final
MAX_RETRIES = 3
RETRY_DELAY_S = 5
# Polite spacing between bbref fetches on cache miss. Their fair-use guidance
# asks scrapers not to exceed about one request per second. We default to 1.5s
# which keeps a fresh 15-game slate at roughly 25 seconds total elapsed.
INTER_REQUEST_DELAY_S = 1.5
_last_fetch_ts: float = 0.0

# Full MLB team name → bbref team code. bbref uses historical 3-letter codes
# that often disagree with MLB.com's modern abbreviations (NYA vs NYY,
# SDN vs SD, SLN vs STL, etc.). Source: verified against actual bbref URLs.
BBREF_CODE_FROM_MLB_NAME: dict[str, str] = {
    "Arizona Diamondbacks": "ARI",
    "Athletics": "OAK",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHN",
    "Chicago White Sox": "CHA",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KCA",
    "Los Angeles Angels": "ANA",
    "Los Angeles Dodgers": "LAN",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYN",
    "New York Yankees": "NYA",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SDN",
    "San Francisco Giants": "SFN",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "SLN",
    "Tampa Bay Rays": "TBA",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WAS",
}


def _build_url(home_team: str, game_date: date, dh_game: int = 0) -> str | None:
    code = BBREF_CODE_FROM_MLB_NAME.get(home_team)
    if not code:
        log.warning("No bbref code mapped for home team: %s", home_team)
        return None
    return f"{BBREF_BASE}/{code}/{code}{game_date.strftime('%Y%m%d')}{dh_game}.shtml"


def _fetch_html(url: str) -> str | None:
    """GET the bbref page with browser UA + disk cache. Returns HTML or None.

    Enforces a global minimum spacing of INTER_REQUEST_DELAY_S between cache
    misses so a roundup run does not exceed bbref's polite-use threshold of
    roughly one request per second.
    """
    global _last_fetch_ts
    cached = cache.get(f"bbref_html:{url}")
    if cached:
        return cached
    elapsed = time.monotonic() - _last_fetch_ts
    if elapsed < INTER_REQUEST_DELAY_S:
        time.sleep(INTER_REQUEST_DELAY_S - elapsed)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _last_fetch_ts = time.monotonic()
            resp = httpx.get(
                url,
                headers={"User-Agent": BBREF_USER_AGENT},
                timeout=30,
                follow_redirects=True,
            )
            if resp.status_code == 404:
                log.info("bbref page not found: %s", url)
                return None
            resp.raise_for_status()
            html = resp.text
            cache.set(f"bbref_html:{url}", html, expire=TTL_BBREF_HTML)
            return html
        except Exception as e:
            log.warning(
                "bbref fetch attempt %d/%d failed for %s: %s",
                attempt, MAX_RETRIES, url, e,
            )
            if attempt == MAX_RETRIES:
                return None
            time.sleep(RETRY_DELAY_S)
    return None


# ---------------------------------------------------------------------------
# Table parsers (lightweight regex over the stable data-stat attributes)
# ---------------------------------------------------------------------------


_TABLE_RE_TEMPLATE = r'<table[^>]*id="{tid}"[^>]*>(.*?)</table>'
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
_CELL_RE = re.compile(
    r'<(?:td|th)[^>]*data-stat="([^"]+)"[^>]*>(.*?)</(?:td|th)>',
    re.DOTALL,
)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_NBSP_RE = re.compile(r"&nbsp;|&#160;")


def _clean_cell(raw: str) -> str:
    """Strip HTML tags, decode &nbsp;, collapse whitespace."""
    s = _NBSP_RE.sub(" ", raw)
    s = _TAG_STRIP_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_table(html: str, table_id: str) -> list[dict[str, str]]:
    """Pull rows from a bbref table by id; return list of {data_stat: cell_text}."""
    m = re.search(
        _TABLE_RE_TEMPLATE.format(tid=re.escape(table_id)), html, re.DOTALL,
    )
    if not m:
        return []
    body = m.group(1)
    out: list[dict[str, str]] = []
    for tr in _TR_RE.findall(body):
        cells = _CELL_RE.findall(tr)
        if not cells:
            continue
        row = {stat: _clean_cell(content) for stat, content in cells}
        out.append(row)
    return out


def _parse_play_by_play(html: str) -> list[dict[str, Any]]:
    """Parse the bbref play_by_play table into one row per plate appearance.

    Skips section-header rows (Top of the 1st, ...) and empty rows. Each kept
    row has the fields: inning, score, outs, runners, pitches, runs_outs,
    batting_team, batter, pitcher, wpa_pct, win_expectancy_pct, play_desc.
    """
    rows = _extract_table(html, "play_by_play")
    out: list[dict[str, Any]] = []
    for r in rows:
        # Skip "Top of the 1st" inning header rows (single colspan cell, no
        # data-stat=batter), the table header itself (inning="Inn"), and any
        # row missing the inning-half marker (t1/b1/t2/...).
        inning = r.get("inning") or ""
        if not re.match(r"^[tb]\d{1,2}$", inning):
            continue
        if not r.get("batter") or not r.get("play_desc"):
            continue
        out.append({
            "inning": r.get("inning") or "",
            "score": r.get("score_batting_team") or "",
            "outs": r.get("outs") or "",
            "runners": r.get("runners_on_bases_pbp") or "",
            "pitches": r.get("pitches_pbp") or "",
            "runs_outs": r.get("runs_outs_result") or "",
            "batting_team": r.get("batting_team_id") or "",
            "batter": r.get("batter") or "",
            "pitcher": r.get("pitcher") or "",
            "wpa_pct": r.get("win_probability_added") or "",
            "win_expectancy_pct": r.get("win_expectancy_post") or "",
            "play_desc": r.get("play_desc") or "",
        })
    return out


def _parse_game_scores(html: str, away_team: str, home_team: str) -> dict[str, int]:
    """Map pitcher name → game_score (Bill James) for both teams.

    bbref pitcher tables are id'd `{TeamNameCollapsed}pitching` — strip
    whitespace and punctuation from the full team name.
    """
    out: dict[str, int] = {}
    for team in (away_team, home_team):
        if not team:
            continue
        tid = re.sub(r"[^A-Za-z]", "", team) + "pitching"
        rows = _extract_table(html, tid)
        for r in rows:
            name = r.get("player") or ""
            gsc = r.get("game_score") or ""
            if not name or not gsc or gsc == "GSc":  # skip header
                continue
            if name in {"Team Totals", "Pitching"}:  # bbref aggregate / section rows
                continue
            try:
                out[name] = int(gsc)
            except ValueError:
                continue
    return out


def _parse_game_info(html: str) -> dict[str, str]:
    """Pull a few clean game-info strings from the bbref info block.

    bbref has a free-text block with <strong>Label:</strong> Value pairs.
    Captures weather, attendance, venue, duration, surface, day/night,
    and the umpire crew when present.
    """
    out: dict[str, str] = {}
    pairs = re.findall(
        r"<strong>([^<:]+):?</strong>\s*:?\s*([^<]+?)(?=<)",
        html,
    )
    for label, value in pairs:
        label = label.strip().rstrip(":")
        value = _NBSP_RE.sub(" ", value).strip().lstrip(":").strip().rstrip(".")
        # Decode common HTML entities present in weather strings.
        value = value.replace("&deg;", "°").replace("&amp;", "&")
        if not value:
            continue
        key = label.lower()
        if key in {
            "start time weather", "weather", "attendance", "venue",
            "game duration", "time of game", "umpires",
        }:
            out[key.replace(" ", "_")] = value
    return out


def get_bbref_boxscore(
    game_date: date,
    away_team: str,
    home_team: str,
    dh_game: int = 0,
) -> dict | None:
    """Fetch + parse a bbref box score page for one MLB game.

    Returns:
      {
        "url": str,
        "play_by_play": [
          {"inning": "t1", "outs": "0", "batter": "JJ Wetherholt",
           "pitcher": "Walker Buehler", "wpa_pct": "2%",
           "win_expectancy_pct": "52%", "play_desc": "Strikeout Swinging",
           "runs_outs": "O", "score": "0-0", "runners": "---",
           "pitches": "4,(1-2) CBS.S", "batting_team": "STL"},
          ...
        ],
        "game_scores": {"Walker Buehler": 60, ...},
        "game_info": {"start_time_weather": "68° F, Wind 8mph...", ...},
      }
    Returns None when the URL cannot be built (unmapped team) or the page is
    unavailable / not yet posted.
    """
    url = _build_url(home_team, game_date, dh_game)
    if not url:
        return None
    html = _fetch_html(url)
    if not html:
        return None
    return {
        "url": url,
        "play_by_play": _parse_play_by_play(html),
        "game_scores": _parse_game_scores(html, away_team, home_team),
        "game_info": _parse_game_info(html),
    }


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    # python -m app.services.bbref_boxscore 2026-05-10 "St. Louis Cardinals" "San Diego Padres"
    d = date.fromisoformat(sys.argv[1])
    away = sys.argv[2]
    home = sys.argv[3]
    data = get_bbref_boxscore(d, away, home)
    print(json.dumps(data, indent=2, default=str))
