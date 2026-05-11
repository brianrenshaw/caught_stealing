#!/usr/bin/env python3
"""Daily MLB roundup post for Blot.

Lists every regular-season game from the previous day with a Claude-generated
2-3 sentence summary, the inning-by-inning line score, the top WPA swings,
and current MLB standings at the top.

Pure data tables (standings, line scores, key-swing bullets) are rendered in
Python from the Savant gamefeed and MLB Stats API. Claude only writes the
per-game prose summary, which keeps the hallucination surface tiny and
removes the need for a fact-checker step on day one.

Usage:
    uv run python -m scripts.mlb_daily_roundup
    uv run python -m scripts.mlb_daily_roundup --date 2026-05-11
    uv run python -m scripts.mlb_daily_roundup --force
    uv run python -m scripts.mlb_daily_roundup --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import statsapi
from dotenv import load_dotenv

from app.services.cardinals_postgame import _retry
from app.services.mlb_og_banner import generate_mlb_og_banner
from app.services.mlb_roundup import get_mlb_roundup
from scripts.cardinals_daily_report import _defeat_blot_heading_titlecase
from scripts.daily_analysis import _invoke_claude_cli
from scripts.factcheck_mlb_roundup import FactCheckResult, factcheck_summaries

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = PROJECT_ROOT / "data" / "content"
ANALYSIS_DIR = CONTENT_DIR / "analysis"
# Reports that fail fact-check twice land here so the downstream pipeline
# does not pick them up; the 4 AM verifier reads this dir to escalate.
FACTCHECK_FAILED_DIR = ANALYSIS_DIR / "factcheck_failed"
BLOT_POSTS_DIR = Path(
    "/Users/brianrenshaw/Library/CloudStorage/"
    "Dropbox-Brianrenshawmedia/Brian Renshaw/Apps/Blot/Posts"
)
BLOT_MLB_DIR = BLOT_POSTS_DIR / "MLB"

load_dotenv(PROJECT_ROOT / ".env")

MODEL = "claude-opus-4-7"
USE_CLAUDE_CLI = os.getenv("DAILY_ANALYSIS_USE_CLI", "1") == "1"
REPORT_SLUG = "mlb-roundup"
# Cap on fact-check + surgical-edit iterations before quarantine. The 3 AM cron
# tolerates the runtime in exchange for converging on a publishable post.
MAX_FACTCHECK_ATTEMPTS = 6

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Standings order: NL first, AL second. NL Central leads (user preference).
DIVISIONS: list[str] = [
    "National League Central",
    "National League East",
    "National League West",
    "American League East",
    "American League Central",
    "American League West",
]


# ---------------------------------------------------------------------------
# Standings rendering
# ---------------------------------------------------------------------------


def fetch_rich_standings() -> list[dict]:
    """Pull standings with streak + L10 + full team/division names.

    Uses the raw `statsapi.get("standings", ...)` endpoint with the team
    hydrate so we get the full team name (e.g. "Tampa Bay Rays") and division
    name ("American League East"). The simpler `statsapi.standings_data`
    helper omits streak and L10, which is why we go to the rich endpoint
    directly.
    """
    data = _retry(
        statsapi.get,
        "standings",
        {"leagueId": "103,104", "hydrate": "team(division)"},
    )
    if not data:
        return []
    rows: list[dict] = []
    for record in data.get("records", []):
        for tr in record.get("teamRecords", []):
            team = tr.get("team") or {}
            league_record = tr.get("leagueRecord") or {}
            streak = tr.get("streak") or {}
            last_ten = next(
                (s for s in (tr.get("records") or {}).get("splitRecords", [])
                 if s.get("type") == "lastTen"),
                {},
            )
            division = team.get("division") or {}
            rows.append({
                "team": team.get("name") or "?",
                "team_id": team.get("id"),
                "division": division.get("name") or "?",
                "wins": league_record.get("wins") or 0,
                "losses": league_record.get("losses") or 0,
                "pct": league_record.get("pct") or ".000",
                "gb": tr.get("gamesBack") or "-",
                "streak": streak.get("streakCode") or "",
                "l10": f"{last_ten.get('wins', 0)}-{last_ten.get('losses', 0)}",
            })
    return rows


def render_standings(standings: list[dict]) -> str:
    """Render the six MLB divisions as stacked markdown tables.

    Columns: Team, W-L, PCT, GB, L10, Streak. Division order is controlled
    by the DIVISIONS constant — NL leads, NL Central first.
    """
    if not standings:
        return "## Standings\n\n*Standings unavailable.*\n"

    by_div: dict[str, list[dict]] = {}
    for row in standings:
        by_div.setdefault(row.get("division") or "", []).append(row)
    for rows in by_div.values():
        rows.sort(key=lambda r: float((r.get("pct") or ".000") or 0), reverse=True)

    lines: list[str] = ["## Standings", ""]
    for div in DIVISIONS:
        rows = by_div.get(div)
        if not rows:
            continue
        lines.append(f"### {div}")
        lines.append("")
        lines.append("| Team | W-L | PCT | GB | L10 | Streak |")
        lines.append("|------|----:|----:|---:|-----|--------|")
        for r in rows:
            team = r.get("team", "?")
            w = r.get("wins", 0)
            losses = r.get("losses", 0)
            pct = r.get("pct") or ".000"
            gb = r.get("gb", "-") or "-"
            l10 = r.get("l10", "")
            streak = r.get("streak", "")
            lines.append(
                f"| {team} | {w}-{losses} | {pct} | {gb} | {l10} | {streak} |"
            )
        lines.append("")
    return "\n".join(lines)


def build_record_map(standings: list[dict]) -> dict[str, dict]:
    """Index standings by full team name for per-game augmentation.

    Returns {team_name: {"record", "pct", "gb", "streak", "l10"}}.
    """
    out: dict[str, dict] = {}
    for r in standings:
        name = r.get("team")
        if not name:
            continue
        out[name] = {
            "record": f"{r.get('wins', 0)}-{r.get('losses', 0)}",
            "pct": r.get("pct"),
            "gb": r.get("gb"),
            "streak": r.get("streak"),
            "l10": r.get("l10"),
        }
    return out


# ---------------------------------------------------------------------------
# Per-game rendering
# ---------------------------------------------------------------------------


def _game_header(game: dict) -> str:
    """`### [Marlins 5, Nationals 2 at loanDepot park](savant_url)`.

    Winner-first AP newspaper convention. When the game went to extras,
    append `(N inn)` after the scores. The whole header is wrapped in a
    markdown link to the Savant gamefeed page. Venue is joined with "at"
    rather than an em dash per the project's Trust the Reader rules.
    """
    away_short = game.get("away_short") or "?"
    home_short = game.get("home_short") or "?"
    away_r = game.get("away_score")
    home_r = game.get("home_score")
    venue = game.get("venue") or ""
    savant_url = game.get("savant_url")

    # Detect extra innings from the line score.
    innings = (game.get("line_score") or {}).get("innings") or []
    extras = f" ({len(innings)} inn)" if len(innings) > 9 else ""

    # Winner first. Tie keeps away-first (rare, extra-innings tied game called).
    if home_r is not None and away_r is not None and home_r > away_r:
        score_str = f"{home_short} {home_r}, {away_short} {away_r}{extras}"
    elif away_r is not None and home_r is not None and away_r > home_r:
        score_str = f"{away_short} {away_r}, {home_short} {home_r}{extras}"
    else:
        score_str = f"{away_short} {away_r} at {home_short} {home_r}{extras}"

    label = f"{score_str} at {venue}" if venue else score_str
    if savant_url:
        return f"### [{label}]({savant_url})"
    return f"### {label}"


def render_line_score(game: dict) -> str:
    """Inning-by-inning line score as a markdown table."""
    ls = game.get("line_score") or {}
    innings = ls.get("innings") or []
    totals = ls.get("totals") or {}
    if not innings:
        return ""

    away_abbr = game.get("away_abbr") or "AWY"
    home_abbr = game.get("home_abbr") or "HOM"

    header_cells = [""] + [str(inn.get("num") or "") for inn in innings] + ["R", "H", "E"]
    sep_cells = ["---"] + ["---:"] * len(innings) + ["---:", "---:", "---:"]
    away_cells = [away_abbr] + [
        _fmt_inning_runs((inn.get("away") or {}).get("runs")) for inn in innings
    ] + [
        _fmt_total((totals.get("away") or {}).get("R")),
        _fmt_total((totals.get("away") or {}).get("H")),
        _fmt_total((totals.get("away") or {}).get("E")),
    ]
    home_cells = [home_abbr] + [
        _fmt_inning_runs((inn.get("home") or {}).get("runs")) for inn in innings
    ] + [
        _fmt_total((totals.get("home") or {}).get("R")),
        _fmt_total((totals.get("home") or {}).get("H")),
        _fmt_total((totals.get("home") or {}).get("E")),
    ]
    return (
        "| " + " | ".join(header_cells) + " |\n"
        "| " + " | ".join(sep_cells) + " |\n"
        "| " + " | ".join(away_cells) + " |\n"
        "| " + " | ".join(home_cells) + " |"
    )


def _fmt_inning_runs(v) -> str:
    if v is None or v == "":
        return "·"
    return str(v)


def _fmt_total(v) -> str:
    if v is None or v == "":
        return "-"
    return str(v)


def render_decisions(game: dict) -> str:
    """WP / LP / SV line. The Savant link now lives in the game header."""
    parts: list[str] = []
    wp = game.get("winning_pitcher")
    lp = game.get("losing_pitcher")
    sv = game.get("save_pitcher")
    if wp:
        parts.append(f"WP: {wp}.")
    if lp:
        parts.append(f"LP: {lp}.")
    if sv:
        parts.append(f"SV: {sv}.")
    return " ".join(parts)


def render_key_swings(game: dict) -> str:
    """Top WPA swings as a bullet list."""
    swings = game.get("key_swings") or []
    if not swings:
        return ""
    lines: list[str] = ["**Key swings**"]
    for s in swings:
        inning = s.get("inning_half") or "?"
        delta = s.get("wpa_delta_pct")
        delta_str = f"{'+' if (delta or 0) >= 0 else ''}{delta}%" if delta is not None else "?"
        batter = s.get("batter") or "?"
        pitcher = s.get("pitcher") or "?"
        event = s.get("event") or ""
        # Compact context: EV mph + pitch type @ velo
        ctx_bits: list[str] = []
        if s.get("ev_mph") is not None:
            ctx_bits.append(f"{s['ev_mph']} mph EV")
        if s.get("pitch_type") and s.get("pitch_velo_mph") is not None:
            ctx_bits.append(f"{s['pitch_type']} {s['pitch_velo_mph']}")
        ctx = f" ({', '.join(ctx_bits)})" if ctx_bits else ""
        lines.append(
            f"- {inning} {delta_str}, {batter} {event} off {pitcher}{ctx}"
        )
    return "\n".join(lines)


def render_game_block(game: dict, summary: str | None) -> str:
    """One H3 block per game: header, prose summary, line score, decisions, swings."""
    parts: list[str] = [_game_header(game), ""]
    if summary:
        parts.append(summary.strip())
        parts.append("")
    ls = render_line_score(game)
    if ls:
        parts.append(ls)
        parts.append("")
    decisions = render_decisions(game)
    if decisions:
        parts.append(decisions)
        parts.append("")
    swings = render_key_swings(game)
    if swings:
        parts.append(swings)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Claude prompt — prose summaries only
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = (
    "You are a baseball beat writer. For each MLB game in the supplied JSON, "
    "write a 3-4 sentence factual summary. Stick STRICTLY to the data in the "
    "JSON for that game — do not invent stats, scores, player names, pitch "
    "velocities, season totals, or context that is not in the JSON. If a "
    "field is missing, omit that detail rather than guess.\n\n"
    "HARD RULE — DO NOT DERIVE OR INFER NUMBERS:\n"
    "Every numeric claim in your prose must come from an explicit numeric "
    "field in the JSON. Do not count, sum, or compute values yourself.\n"
    "- RBI counts on a specific play: use the `rbi` field on that play in\n"
    "  key_swings / scoring_plays. Do NOT call a homer 'two-run' or 'three-run'\n"
    "  unless `rbi` confirms it. rbi=1 → 'solo homer'; rbi=2 → 'two-run homer'.\n"
    "- TOTAL RBI for a player across the game: only assert this if the player's\n"
    "  `batting_line` in top_performers explicitly contains an 'N RBI' segment\n"
    "  (e.g., '3-4 | HR, 2 RBI'). If batting_line lists hits/walks but no RBI\n"
    "  (e.g., '2-5 | 2 2B, BB, K'), do NOT state a total RBI count for that\n"
    "  player. Describe what they did ('two doubles') without inventing a sum.\n"
    "- RUNS PER INNING ('a five-run fifth', 'three-run sixth', 'four-run frame'):\n"
    "  only assertable if the `line_score.innings` entry for that inning + team\n"
    "  shows that exact runs value. Look at line_score.innings[i].away.runs or\n"
    "  .home.runs. If the number you want to write does not appear there, do\n"
    "  NOT characterize the inning by run total. Describe the scoring plays\n"
    "  individually instead, or simply say 'in the fifth'.\n"
    "- PITCHER EXIT / 'CHASED' / 'KNOCKED OUT' / 'PULLED EARLY' claims: only\n"
    "  assertable from the pitcher's `pitching_line` in top_performers (which\n"
    "  shows IP) AND the bbref `play_by_play` (which shows the last inning a\n"
    "  pitcher appears as `pitcher`). Do NOT infer an early exit from when a\n"
    "  team scored or from prose context. Cross-check both fields. If unsure,\n"
    "  state IP only ('Wrobleski allowed five runs over 5.2 innings').\n"
    "- OUTS CONTEXT for a play ('two-out homer', 'leadoff single', 'with two\n"
    "  on and one out'): only assertable from the bbref `play_by_play` row for\n"
    "  that play, reading the `outs` (outs after the play) and `runners` (base\n"
    "  state before the play) fields. Do NOT infer from where in the inning\n"
    "  the play appeared. If the data is not there, drop the outs detail.\n"
    "- TEAM ATTRIBUTION for stat lines: read the `team_id` on top_performers\n"
    "  entries. team_id maps to a specific MLB team; the player belongs to\n"
    "  THAT team in the game, not the opposing one. A double off a Cleveland\n"
    "  pitcher came from a non-Cleveland batter; do not attribute the batter\n"
    "  to Cleveland.\n"
    "- Times on base: use the `batting_line` summary string verbatim if you must\n"
    "  cite it (e.g., '2-3 with two walks'). Do NOT sum hits + walks yourself.\n"
    "- Innings, outs, scores: only cite when present as a field. Do not count\n"
    "  runs by inning from the line score yourself.\n"
    "- If you find yourself adding numbers in your head, stop and either find\n"
    "  the explicit field or omit the claim.\n\n"
    "Each summary should cover, when the data supports it:\n"
    "- the final score and venue in context (close game, blowout, walk-off, extras)\n"
    "- the winning and losing pitcher (and saver if listed)\n"
    "- ONE decisive moment from the key_swings list (highest |WPA Δ|), with the\n"
    "  EV / pitch type detail if available\n"
    "- when a play in key_swings or scoring_plays carries `season_total`, surface\n"
    "  it after the player + event ('Caminero homered (11)' or 'his 11th homer\n"
    "  of the year', 'Schwarber's 15th HR'). Only use the number that appears\n"
    "  in the JSON — never invent or round season totals.\n"
    "- ONE or TWO notable stat lines from top_performers — phrase them naturally\n"
    "  ('Snell struck out 10 over 6 shutout innings on 92 pitches', 'Betts went\n"
    "  3-for-4 with a homer and two RBI'). top_performers lines come directly\n"
    "  from MLB's official box; do not paraphrase the numbers wrong.\n"
    "- optionally a pitcher's Bill James game_score from `bbref.game_scores`\n"
    "  when it is notable: 70+ is dominant, 80+ is elite. Phrase as 'a 78\n"
    "  game score' or 'his 64 game score'. Only cite the integer that appears\n"
    "  in the dict for that exact pitcher name.\n"
    "- a record/streak note ONLY when it is genuinely notable from the team_records\n"
    "  field: a 4+ game streak (W4+, L4+), an extreme L10 (8-2 or worse than 2-8),\n"
    "  or first place / cellar-level standing. Skip records that are unremarkable.\n"
    "- a LEAGUE-WIDE comparison (e.g., 'league-best record', 'second-worst in\n"
    "  baseball', 'tied with the Yankees for the AL lead') is allowed ONLY when\n"
    "  it can be verified against the full `mlb_standings` block at the top of\n"
    "  the prompt. Do not assert league-wide rankings if mlb_standings does not\n"
    "  unambiguously support them.\n\n"
    "Write in past tense. Keep each summary tight, 3-4 sentences, never more "
    "than ~85 words. Do not write player names with hyphenated team prefixes "
    "(e.g., 'Padres-Tatis'). No editorializing, no fan-takeaway phrasing, no "
    "season-total fabrications (only cite numbers that appear in the JSON).\n\n"
    "STYLE RULES (from the project's Trust the Reader guide):\n"
    "- Never use em dashes (—). Replace with periods or commas, or restructure.\n"
    "  This rule applies to every character you output, including parenthetical\n"
    "  asides and appositives. A common Claude habit is to use ' — ' to set off\n"
    "  a clause; don't. Use commas or split into two sentences.\n"
    "- Do not use corrective contrast ('not X but Y', 'the issue isn't X, it's Y').\n"
    "  State the actual fact directly. Trust the reader to infer what it excludes.\n"
    "- Do not open a sentence with false-transition phrases ('Here's the thing',\n"
    "  'What's interesting is', 'The reality is', 'To be clear', 'At its core').\n"
    "  Every sentence must do connective work; don't announce importance.\n"
    "- Do not restate a point in different words. State the claim, move on.\n"
    "- Drop the comma before 'and' / 'but' in compound sentences. Keep oxford\n"
    "  commas in lists of three or more.\n\n"
    "Also write a single one-sentence `post_summary` (~120 chars) describing "
    "the slate as a whole — the standout headline of the day. Examples:\n"
    "  'Walk-offs in San Diego and Atlanta headline a 15-game slate.'\n"
    "  'Skenes whiffs 13, Ohtani goes deep twice in a 12-game Sunday card.'\n\n"
    "Return JSON with this exact shape and nothing else (no markdown fences, "
    "no prose outside the JSON):\n"
    "{\n"
    '  "post_summary": "...",\n'
    '  "summaries": { "<game_pk>": "...", "<game_pk>": "...", ... }\n'
    "}"
)


def _trim_game_for_prompt(game: dict) -> dict:
    """Strip per-game payload down to the fields Claude needs for a summary."""
    bbref = game.get("bbref") or {}
    # bbref PBP is verbose (~80 rows); pass through as-is — it's the secondary
    # ground truth for the fact-checker and is small enough not to bloat tokens
    # excessively (~6KB per game, 90KB across the slate, vs ~130KB total context).
    bbref_trimmed = {
        "play_by_play": bbref.get("play_by_play") or [],
        "game_scores": bbref.get("game_scores") or {},
    }
    return {
        "game_pk": game.get("game_pk"),
        "away_team": game.get("away_team"),
        "home_team": game.get("home_team"),
        "away_score": game.get("away_score"),
        "home_score": game.get("home_score"),
        "venue": game.get("venue"),
        "winning_pitcher": game.get("winning_pitcher"),
        "losing_pitcher": game.get("losing_pitcher"),
        "save_pitcher": game.get("save_pitcher"),
        "innings_played": len((game.get("line_score") or {}).get("innings") or []),
        "key_swings": (game.get("key_swings") or [])[:3],
        "scoring_plays": (game.get("scoring_plays") or [])[:4],
        "hardest_hit": (game.get("hardest_hit") or [])[:2],
        "top_pitches": (game.get("top_pitches") or [])[:2],
        "top_performers": game.get("top_performers") or [],
        "team_records": game.get("team_records") or {},
        "bbref": bbref_trimmed,
        "game_context": {
            k: v for k, v in (game.get("game_context") or {}).items()
            if k in {"weather", "wind", "attendance", "linescore_note", "final_play"}
        },
    }


def _trim_standings_for_prompt(standings: list[dict]) -> list[dict]:
    """Compact standings rows for inclusion in writer + fact-checker prompts.

    Drops the team_id (consumers match by name) and keeps just the fields
    needed to verify cross-team claims like 'league-best record' or 'second-
    worst team in baseball'.
    """
    return [
        {
            "team": r.get("team"),
            "division": r.get("division"),
            "wins": r.get("wins"),
            "losses": r.get("losses"),
            "pct": r.get("pct"),
            "gb": r.get("gb"),
            "streak": r.get("streak"),
            "l10": r.get("l10"),
        }
        for r in standings
    ]


def build_prompt(game_date: date, games: list[dict], standings: list[dict]) -> str:
    """Build the Claude user message: full standings + per-game payloads."""
    trimmed = [_trim_game_for_prompt(g) for g in games]
    trimmed_standings = _trim_standings_for_prompt(standings)
    return (
        f"Date covered: {game_date.strftime('%B %-d, %Y')}\n"
        f"Games: {len(trimmed)}\n\n"
        "Full MLB standings (use ONLY for league-wide / cross-team claims like "
        "'league-best record', 'leads the AL', 'second-worst team in baseball' — "
        "the per-game `team_records` block remains the source for the two "
        "teams playing each game):\n\n"
        "```json\n"
        + json.dumps(trimmed_standings, indent=2, default=str)
        + "\n```\n\n"
        "Per-game JSON payloads (write a summary for each, keyed by game_pk):\n\n"
        "```json\n"
        + json.dumps(trimmed, indent=2, default=str)
        + "\n```\n"
    )


def _parse_claude_response(text: str) -> dict:
    """Extract the JSON dict from Claude's response.

    Claude sometimes wraps JSON in ```json fences despite the prompt asking
    it not to. Strip those defensively before parsing.
    """
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        log.error("Failed to parse Claude JSON response: %s", e)
        log.error("Response was: %s", text[:500])
        return {}


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------


def build_post_body(
    game_date: date,
    standings: list[dict],
    games: list[dict],
    summaries: dict[str, str],
) -> str:
    """Assemble the full post body — games first, standings at the bottom."""
    parts: list[str] = [f"## Games, {game_date.strftime('%B %-d, %Y')}", ""]
    if not games:
        parts.append("*No games played.*")
    else:
        for game in games:
            pk = str(game.get("game_pk") or "")
            summary = summaries.get(pk) or summaries.get(int(pk)) if pk.isdigit() else None
            parts.append(render_game_block(game, summary))
    parts.append("")
    parts.append(render_standings(standings))
    return "\n".join(parts).rstrip() + "\n"


def write_local_report(
    today: date,
    body: str,
    n_games: int,
    in_toks: int,
    out_toks: int,
) -> Path:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ANALYSIS_DIR / f"{today.isoformat()}_{REPORT_SLUG}.md"
    frontmatter = (
        "---\n"
        f"title: \"MLB Roundup, {today.strftime('%B %d, %Y')}\"\n"
        f"type: {REPORT_SLUG}\n"
        f"date: {today.isoformat()}\n"
        f"generated_at: {datetime.now(timezone.utc).isoformat()}\n"
        f"game_count: {n_games}\n"
        f"input_tokens: {in_toks}\n"
        f"output_tokens: {out_toks}\n"
        "---\n\n"
        f"# MLB Roundup, {today.strftime('%B %d, %Y')}\n\n"
    )
    out_path.write_text(frontmatter + body, encoding="utf-8")
    return out_path


def publish_to_blot(
    today: date,
    game_date: date,
    body: str,
    post_summary: str,
    n_games: int,
) -> Path | None:
    """Drop the Blot post into the MLB/ subfolder under Posts/.

    Blot treats subfolders under Posts/ as tags applied to all posts within,
    so this single line plus mkdir gives every roundup an `MLB` tag.
    """
    if not BLOT_POSTS_DIR.exists():
        log.warning("Blot Posts folder not found at %s — skipping publish", BLOT_POSTS_DIR)
        return None

    BLOT_MLB_DIR.mkdir(parents=True, exist_ok=True)

    title = f"MLB Roundup, {game_date.strftime('%B %-d, %Y')}"
    fallback_summary = f"{n_games} games on {game_date.strftime('%B %-d')}."
    summary = post_summary.strip() if post_summary else fallback_summary
    header = (
        f"Title: {title}\n"
        f"Date: {today.isoformat()}\n"
        f"Summary: {summary}\n"
        f"Link: mlb-roundup-{today.isoformat()}\n"
        "\n"
    )

    # Strip the leading H1 — Blot renders the title from the metadata.
    stripped = re.sub(r"^\s*#\s+.+?\n+", "", body.lstrip(), count=1)

    # Generate the per-post OG banner and embed it as the first inline image.
    # Underscore-prefixed filename keeps Blot from publishing the PNG as its
    # own photo post (per blot.im/how/files/images). Sibling placement inside
    # MLB/ lets Blot resolve the relative path and pick it up as
    # {{#thumbnail.large}}, which lights up the iMessage / social rich-card
    # preview via the og:image tags in head.html. Wrapped: a banner failure
    # never blocks the publish itself.
    banner_name = f"_{today.isoformat()}-mlb-roundup.png"
    try:
        generate_mlb_og_banner(game_date, n_games, BLOT_MLB_DIR / banner_name)
        stripped = f"![MLB Roundup — {game_date.strftime('%B %-d, %Y')}]({banner_name})\n\n{stripped}"
        log.info("Generated MLB OG banner: %s", banner_name)
    except Exception as exc:  # noqa: BLE001 — banner is enhancement-only
        log.warning("MLB OG banner generation failed (%s); publishing without it", exc)

    stripped = _defeat_blot_heading_titlecase(stripped)

    post_path = BLOT_MLB_DIR / f"{today.isoformat()}-mlb-roundup.md"
    post_path.write_text(header + stripped, encoding="utf-8")
    log.info("Published to Blot: %s (title: %s)", post_path, title)
    return post_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(
    force: bool = False,
    dry_run: bool = False,
    report_date: date | None = None,
    skip_factcheck: bool = False,
) -> None:
    today = report_date or date.today()
    game_date = today - timedelta(days=1)
    out_path = ANALYSIS_DIR / f"{today.isoformat()}_{REPORT_SLUG}.md"

    if out_path.exists() and not force and not dry_run:
        log.info("Today's roundup already exists at %s (use --force to regenerate)", out_path)
        return

    log.info("Fetching MLB standings (with streak + L10)...")
    standings = fetch_rich_standings()
    log.info("Loaded %d team standings rows", len(standings))

    log.info("Fetching per-game payloads for %s...", game_date.isoformat())
    games = get_mlb_roundup(game_date)
    log.info("Built %d game payloads", len(games))

    # Augment each game payload with both teams' current records (W-L, PCT,
    # GB, streak, L10) so Claude can sprinkle in streak / hot-cold notes
    # when the data warrants it. Keyed by full team name.
    record_map = build_record_map(standings)
    for g in games:
        g["team_records"] = {
            "away": record_map.get(g.get("away_team") or "", {}),
            "home": record_map.get(g.get("home_team") or "", {}),
        }

    if not games:
        log.warning("No completed games on %s — writing standings-only post", game_date.isoformat())

    user_message = build_prompt(game_date, games, standings)

    if dry_run:
        log.info("=== DRY RUN ===")
        log.info("System prompt: %d chars", len(SYSTEM_PROMPT))
        log.info("User message: %d chars (~%d tokens)", len(user_message), len(user_message) // 4)
        log.info("Standings rows: %d", len(standings))
        log.info("Games: %d", len(games))
        # Render a partial post (no Claude summaries) so the user can inspect the layout.
        preview = build_post_body(game_date, standings, games, summaries={})
        preview_path = ANALYSIS_DIR / f"{today.isoformat()}_{REPORT_SLUG}.dryrun.md"
        ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        preview_path.write_text(preview, encoding="utf-8")
        log.info("Wrote layout preview (no summaries): %s", preview_path)
        return

    if not USE_CLAUDE_CLI:
        log.error("Roundup only supports CLI (subscription) mode currently. Aborting.")
        return

    if games:
        log.info("Generating per-game summaries via Claude Code subscription (claude -p)...")
        try:
            text, in_toks, out_toks, stop = _invoke_claude_cli(
                MODEL, SYSTEM_PROMPT, user_message
            )
        except Exception as e:
            log.error("Roundup generation failed: %s", e)
            return
        log.info(
            "Generated: %d chars, %d input tokens, %d output tokens (stop: %s)",
            len(text), in_toks, out_toks, stop,
        )
        parsed = _parse_claude_response(text)
        summaries = parsed.get("summaries") or {}
        post_summary = parsed.get("post_summary") or ""
        summaries = {str(k): v for k, v in summaries.items()}
    else:
        in_toks = out_toks = 0
        summaries = {}
        post_summary = ""

    # ----- Fact-check the per-game summaries -----
    # Compares every numeric / factual claim in each summary against the same
    # per-game JSON the writer saw + the full standings + bbref PBP. On fail,
    # we apply a SURGICAL EDIT retry (only the flagged games get touched) and
    # re-check. We keep iterating up to MAX_FACTCHECK_ATTEMPTS so the 3 AM cron
    # converges on a publishable post rather than landing in factcheck_failed/.
    if games and skip_factcheck:
        log.warning("--skip-factcheck flag set, bypassing verification.")
    elif games:
        trimmed_for_check = [_trim_game_for_prompt(g) for g in games]
        trimmed_standings_for_check = _trim_standings_for_prompt(standings)

        attempt = 0
        while True:
            attempt += 1
            check = factcheck_summaries(
                summaries, trimmed_for_check, trimmed_standings_for_check,
            )
            if check.passed:
                log.info("Fact-check PASSED on attempt %d.", attempt)
                break

            log.warning(
                "Fact-check FAILED on attempt %d. %d issues.",
                attempt, len(check.issues),
            )
            for i in check.issues:
                log.warning(
                    "  - [pk=%s %s] %s — %s",
                    i.game_pk, i.category, i.claim, i.why_suspect,
                )

            if attempt >= MAX_FACTCHECK_ATTEMPTS:
                log.error(
                    "Hit MAX_FACTCHECK_ATTEMPTS (%d). Quarantining.",
                    MAX_FACTCHECK_ATTEMPTS,
                )
                _quarantine_failed_report(
                    today, summaries,
                    build_post_body(game_date, standings, games, summaries),
                    in_toks, out_toks, check,
                )
                return

            log.info(
                "Applying surgical edits (attempt %d → %d)...",
                attempt, attempt + 1,
            )
            retry_message = _build_retry_message(summaries, post_summary, check)
            try:
                text2, in2, out2, _stop2 = _invoke_claude_cli(
                    MODEL, SYSTEM_PROMPT, retry_message,
                )
            except Exception as e:
                log.error("Retry edit failed: %s. Quarantining.", e)
                _quarantine_failed_report(
                    today, summaries,
                    build_post_body(game_date, standings, games, summaries),
                    in_toks, out_toks, check,
                )
                return

            if not text2:
                log.error("Empty retry response. Quarantining.")
                _quarantine_failed_report(
                    today, summaries,
                    build_post_body(game_date, standings, games, summaries),
                    in_toks, out_toks, check,
                )
                return

            parsed2 = _parse_claude_response(text2)
            new_summaries = parsed2.get("summaries") or {}
            new_summaries = {str(k): v for k, v in new_summaries.items()}
            new_post_summary = parsed2.get("post_summary") or post_summary
            in_toks += in2
            out_toks += out2

            # Merge: keep retry summaries (the surgical edits), fall back to
            # the prior versions for any pk the retry omitted.
            merged = dict(summaries)
            merged.update(new_summaries)
            summaries = merged
            post_summary = new_post_summary

    body = build_post_body(game_date, standings, games, summaries)
    local_path = write_local_report(today, body, len(games), in_toks, out_toks)
    log.info("Wrote local report: %s", local_path)

    try:
        publish_to_blot(today, game_date, body, post_summary, len(games))
    except Exception as e:
        log.warning("Blot publish failed (non-fatal): %s", e)


def _build_retry_message(
    previous_summaries: dict[str, str],
    previous_post_summary: str,
    check: FactCheckResult,
) -> str:
    """Build a SURGICAL-EDIT retry message for the per-game summaries.

    Sends Claude only the summaries that had fact-check issues, plus the
    specific phrase-level problems, and asks for ONLY those summaries to come
    back fixed. Untouched summaries are preserved verbatim from the prior
    pass. Avoids the full-regeneration retry's failure modes (wasted tokens
    + fresh inferences in untouched paragraphs).
    """
    by_game = check.issues_by_game()
    blocks: list[str] = []
    for pk, issues in by_game.items():
        prev = previous_summaries.get(str(pk), "(previous summary missing)")
        issue_lines = []
        for i in issues:
            line = f'  - Claim: "{i.claim}"\n    Why suspect: {i.why_suspect}'
            if i.json_value_if_close:
                line += f"\n    Actual value in JSON: {i.json_value_if_close}"
            issue_lines.append(line)
        blocks.append(
            f"### game_pk = {pk}\n\n"
            f"Previous summary:\n```\n{prev}\n```\n\n"
            f"Issues to fix in this summary:\n"
            + "\n\n".join(issue_lines)
        )

    return (
        "You are applying SURGICAL EDITS to specific per-game summaries from a "
        "previous fact-check pass. For each game listed below, the summary text "
        "contained phrase-level errors. Edit ONLY the flagged phrases.\n\n"
        + "\n\n---\n\n".join(blocks)
        + "\n\n---\n\n"
        "INSTRUCTIONS:\n"
        "- Return ONLY the games listed above (do not include unflagged games; "
        "the runner will merge your fixes with the previously passing summaries).\n"
        "- For each flagged claim: (a) if an actual JSON value is given, replace "
        "the wrong value with that value; (b) if no JSON value is given, REMOVE "
        "the claim entirely (delete the phrase or sentence). Choose whichever "
        "produces the cleanest sentence.\n"
        "- Do NOT rewrite paragraphs or clauses that contain no flagged claims. "
        "Leave the rest of each summary character-for-character identical to its "
        "previous version.\n"
        "- Do NOT add new sentences, new prose, or new claims.\n"
        "- Do NOT change the `post_summary` unless one of its claims is flagged "
        "(keep `post_summary` verbatim from the previous pass unless told to fix it).\n"
        "- Return JSON with this exact shape and nothing else (no markdown fences):\n"
        "{\n"
        f'  "post_summary": "{previous_post_summary}",\n'
        '  "summaries": { "<game_pk>": "<edited summary>", ... }\n'
        "}\n"
        "Include only the keys for the games listed above in `summaries`."
    )


def _quarantine_failed_report(
    today: date,
    summaries: dict[str, str],
    body: str,
    in_toks: int,
    out_toks: int,
    check: FactCheckResult,
) -> None:
    """Move a fact-check-failed roundup out of the normal pipeline path.

    Writes the failing MD and a sibling `.factcheck.json` log to
    FACTCHECK_FAILED_DIR so the report is preserved for review but excluded
    from the glob the downstream bash pipeline uses, and skips Blot publish.
    """
    FACTCHECK_FAILED_DIR.mkdir(parents=True, exist_ok=True)
    failed_md = FACTCHECK_FAILED_DIR / f"{today.isoformat()}_{REPORT_SLUG}.md"
    frontmatter = (
        "---\n"
        f"title: \"MLB Roundup (QUARANTINED), {today.strftime('%B %d, %Y')}\"\n"
        f"type: {REPORT_SLUG}\n"
        f"date: {today.isoformat()}\n"
        f"generated_at: {datetime.now(timezone.utc).isoformat()}\n"
        f"input_tokens: {in_toks}\n"
        f"output_tokens: {out_toks}\n"
        "factcheck_status: failed\n"
        "---\n\n"
    )
    failed_md.write_text(frontmatter + body, encoding="utf-8")

    failed_log = FACTCHECK_FAILED_DIR / f"{today.isoformat()}_{REPORT_SLUG}.factcheck.json"
    failed_log.write_text(json.dumps(check.to_dict(), indent=2), encoding="utf-8")

    log.error(
        "Fact-check FAILED after retry — %d issues remain. Quarantined to %s",
        len(check.issues), failed_md,
    )
    log.error("Issues:\n%s", check.issue_summary())

    # macOS notification so the user sees it before the 4 AM verifier runs.
    try:
        import subprocess

        msg = f"{len(check.issues)} fact-check issues — quarantined to factcheck_failed/"
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{msg}" with title "MLB Roundup BLOCKED" '
                f'subtitle "{today.isoformat()} — see {failed_log.name}"',
            ],
            check=False,
            timeout=5,
        )
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily MLB roundup post for Blot")
    parser.add_argument("--force", action="store_true", help="Regenerate even if today's exists")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview prompt + layout, no Claude call",
    )
    parser.add_argument(
        "--date", dest="report_date", type=date.fromisoformat, default=None,
        help="Override report date (YYYY-MM-DD). The covered slate is this date minus one.",
    )
    parser.add_argument(
        "--skip-factcheck", action="store_true",
        help="Bypass the Opus 4.7 fact-check pass (emergency / debug only)",
    )
    args = parser.parse_args()
    run(
        force=args.force,
        dry_run=args.dry_run,
        report_date=args.report_date,
        skip_factcheck=args.skip_factcheck,
    )


if __name__ == "__main__":
    main()
