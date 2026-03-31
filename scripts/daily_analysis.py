#!/usr/bin/env python3
"""Daily fantasy baseball intelligence report powered by Claude API.

Makes a single comprehensive API call combining expert content analysis
(blogs + podcast transcripts) with league data, then splits the response
into individual section files for the Intel tab and Obsidian.

Usage:
    uv run python -m scripts.daily_analysis              # generate daily intel
    uv run python -m scripts.daily_analysis --dry-run    # print prompt, no API call
    uv run python -m scripts.daily_analysis --force      # regenerate even if today's exists
    uv run python -m scripts.daily_analysis --days 10    # override content window (default: 7 for weekly)

Environment:
    ANTHROPIC_API_KEY must be set in .env for Claude API calls.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = PROJECT_ROOT / "data" / "content"
BLOGS_DIR = CONTENT_DIR / "blogs"
TRANSCRIPTS_DIR = CONTENT_DIR / "transcripts"
ANALYSIS_DIR = CONTENT_DIR / "analysis"
DB_PATH = PROJECT_ROOT / "fantasy_baseball.db"

load_dotenv(PROJECT_ROOT / ".env")

MODEL = "claude-opus-4-6"
SEASON = date.today().year if date.today().month >= 3 else date.today().year - 1

# Sections to split from the combined report.
# Keys are slugified header names, values are the expected ## header text.
SECTIONS = {
    "last-week-recap": "Last Week's Recap",
    "roster-intel": "My Roster Intel",
    "injury-watch": "Injury Watch",
    "matchup-preview": "Matchup Preview",
    "waiver-intel": "Waiver Targets",
    "trade-intel": "Trade Signals",
    "projection-watch": "Projection Watch",
    "around-the-league": "Around the League",
    "cardinals-corner": "Cardinals Corner",
    "sibling-rivalry": "Sibling Rivalry",
    "action-items": "Action Items",
}

# Same format within each section across all report types.
# Only difference is which sections are included.
DAILY_SECTIONS = ["roster-intel", "injury-watch", "around-the-league", "action-items"]
MONDAY_SECTIONS = ["last-week-recap"] + DAILY_SECTIONS
WEEKLY_SECTIONS = [
    "roster-intel",
    "injury-watch",
    "matchup-preview",
    "waiver-intel",
    "trade-intel",
    "projection-watch",
    "around-the-league",
    "cardinals-corner",
    "sibling-rivalry",
    "action-items",
]
WEEKLY_DAY = 5  # Saturday
WEEKLY_CONTENT_DAYS = 7  # How many days of content to include in weekly reports
# Token budget for content. The model needs headroom for system prompt (~2k),
# league data (~50k tokens), and output (16k tokens). With 1M context, target
# ~600k tokens for content (~2.4M chars at ~4 chars/token) to leave comfortable room.
MAX_CONTENT_CHARS = 2_400_000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Content loading
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text."""
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            val = val.strip().strip('"').strip("'")
            meta[key.strip()] = val

    return meta, parts[2].strip()


def get_last_report_time() -> datetime | None:
    """Get the generated_at timestamp of the most recent intel report (daily or weekly)."""
    if not ANALYSIS_DIR.exists():
        return None

    # Check both daily and weekly reports, return the most recent
    for pattern in ["*_daily-intel.md", "*_weekly-intel.md"]:
        for filepath in sorted(ANALYSIS_DIR.glob(pattern), reverse=True):
            try:
                text = filepath.read_text(encoding="utf-8")
                meta, _ = parse_frontmatter(text)
                gen_at = meta.get("generated_at", "")
                if gen_at:
                    return datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
            except Exception:
                pass
    return None


def load_recent_content(since: datetime | None = None) -> list[dict]:
    """Load blog articles and podcast transcripts.

    If `since` is provided, only loads content published after that time.
    If None (first run), loads everything available.
    Full text — no truncation.
    """
    items = []

    for content_dir, content_type in [
        (BLOGS_DIR, "blog"),
        (TRANSCRIPTS_DIR, "transcript"),
    ]:
        if not content_dir.exists():
            continue

        for filepath in sorted(content_dir.glob("*.md"), reverse=True):
            try:
                text = filepath.read_text(encoding="utf-8")
                meta, body = parse_frontmatter(text)

                date_str = meta.get("date", "")
                if not date_str:
                    continue

                try:
                    pub_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    continue

                if since and pub_date < since:
                    continue

                word_count = len(body.split())
                content = body

                items.append(
                    {
                        "title": meta.get("title", filepath.stem),
                        "source_name": meta.get("source_name", meta.get("source", "Unknown")),
                        "url": meta.get("url", ""),
                        "date": date_str,
                        "date_parsed": pub_date,
                        "author": meta.get("author", ""),
                        "content": content,
                        "type": content_type,
                        "filename": filepath.name,
                        "word_count": word_count,
                    }
                )

            except Exception as e:
                log.warning("Failed to read %s: %s", filepath.name, e)

    items.sort(key=lambda x: x["date_parsed"], reverse=True)
    log.info(
        "Loaded %d content items (%d blogs, %d transcripts)",
        len(items),
        sum(1 for i in items if i["type"] == "blog"),
        sum(1 for i in items if i["type"] == "transcript"),
    )
    return items


def build_sources_section(items: list[dict]) -> str:
    """Build the Sources Analyzed section for the report header."""
    podcasts = [i for i in items if i["type"] == "transcript"]
    blogs = [i for i in items if i["type"] == "blog"]

    lines = ["## Sources Analyzed\n"]

    if podcasts:
        lines.append("### Podcasts")
        for p in podcasts:
            pub = p["date_parsed"].strftime("%b %d, %Y")
            if p.get("url"):
                lines.append(f"- **{p['source_name']}** — [{p['title']}]({p['url']}) ({pub})")
            else:
                lines.append(f"- **{p['source_name']}** — {p['title']} ({pub})")
        lines.append("")

    if blogs:
        lines.append("### Blogs")
        for b in blogs:
            pub = b["date_parsed"].strftime("%b %d, %Y")
            if b.get("url"):
                lines.append(f"- **{b['source_name']}** — [{b['title']}]({b['url']}) ({pub})")
            else:
                lines.append(f"- **{b['source_name']}** — {b['title']} ({pub})")
        lines.append("")

    lines.append("---\n")
    return "\n".join(lines)


def build_content_context(items: list[dict]) -> str:
    """Build the content context string for the Claude prompt.

    If the combined content exceeds MAX_CONTENT_CHARS, truncates the longest
    transcripts first (keeping the beginning of each) until the total fits.
    Blog articles are never truncated — they're short and information-dense.
    """
    sections = []
    for item in items:
        type_label = "Podcast Transcript" if item["type"] == "transcript" else "Blog Article"
        header = f'### [{type_label}] "{item["title"]}" — {item["source_name"]} ({item["date_parsed"].strftime("%b %d, %Y")})'
        if item.get("author"):
            header += f" by {item['author']}"
        sections.append({"header": header, "content": item["content"], "type": item["type"]})

    # Check total size and truncate transcripts if needed
    separator = "\n\n---\n\n"
    total_chars = sum(len(s["header"]) + len(s["content"]) for s in sections)
    total_chars += len(separator) * max(len(sections) - 1, 0)

    if total_chars > MAX_CONTENT_CHARS:
        log.warning(
            "Content too large (%d chars, ~%dk tokens). Truncating transcripts to fit.",
            total_chars,
            total_chars // 4000,
        )
        # Sort transcripts by length (longest first) for truncation
        transcripts = [s for s in sections if s["type"] == "transcript"]
        transcripts.sort(key=lambda s: len(s["content"]), reverse=True)

        excess = total_chars - MAX_CONTENT_CHARS
        for t in transcripts:
            if excess <= 0:
                break
            max_len = max(len(t["content"]) - excess, len(t["content"]) // 3)
            cut = len(t["content"]) - max_len
            t["content"] = t["content"][:max_len] + "\n\n[... transcript truncated for length ...]"
            excess -= cut
            log.info("  Truncated: %s (kept %d chars)", t["header"][:60], max_len)

    parts = []
    for s in sections:
        parts.append(f"{s['header']}\n\n{s['content']}")

    return separator.join(parts)


# ---------------------------------------------------------------------------
# League data loading
# ---------------------------------------------------------------------------


def load_league_context(db_path: Path) -> dict | None:
    """Load league data from SQLite. Returns None if no data available."""
    if not db_path.exists():
        log.warning("Database not found at %s", db_path)
        return None

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM rosters")
        if cursor.fetchone()[0] == 0:
            log.warning("No roster data in database — skipping league context")
            conn.close()
            return None

        # My roster with projections
        cursor.execute(
            """
            SELECT p.name, p.team, p.position, r.roster_position,
                   pp.projected_ros_points, pp.steamer_ros_points,
                   pp.surplus_value, pp.positional_rank
            FROM rosters r
            JOIN players p ON r.player_id = p.id
            LEFT JOIN player_points pp ON pp.player_id = p.id
                AND pp.season = ? AND pp.period = 'full_season'
            WHERE r.is_my_team = 1
            ORDER BY pp.projected_ros_points DESC
        """,
            (SEASON,),
        )
        my_roster = [dict(row) for row in cursor.fetchall()]

        # Ithilien's roster (rival)
        cursor.execute(
            """
            SELECT p.name, p.team, p.position, r.team_name,
                   pp.projected_ros_points, pp.surplus_value
            FROM rosters r
            JOIN players p ON r.player_id = p.id
            LEFT JOIN player_points pp ON pp.player_id = p.id
                AND pp.season = ? AND pp.period = 'full_season'
            WHERE LOWER(r.team_name) LIKE '%ithilien%'
            ORDER BY pp.projected_ros_points DESC
        """,
            (SEASON,),
        )
        rival_roster = [dict(row) for row in cursor.fetchall()]

        # Standings
        cursor.execute("""
            SELECT team_name, rank, wins, losses, points_for, points_against, is_my_team
            FROM league_teams
            ORDER BY rank
        """)
        standings = [dict(row) for row in cursor.fetchall()]

        # This week's H2H opponent from matchup snapshot
        opponent_info = None
        opponent_roster = []
        try:
            cursor.execute("""
                SELECT opponent_team_name, opponent_team_id,
                       my_projected_points, opponent_projected_points
                FROM weekly_matchup_snapshots
                ORDER BY id DESC LIMIT 1
            """)
            row = cursor.fetchone()
            if row:
                opponent_info = dict(row)
                # Get opponent's roster
                cursor.execute(
                    """
                    SELECT p.name, p.team, p.position,
                           pp.projected_ros_points, pp.surplus_value
                    FROM rosters r
                    JOIN players p ON r.player_id = p.id
                    LEFT JOIN player_points pp ON pp.player_id = p.id
                        AND pp.season = ? AND pp.period = 'full_season'
                    WHERE r.team_name = ?
                    ORDER BY pp.projected_ros_points DESC
                """,
                    (SEASON, opponent_info["opponent_team_name"]),
                )
                opponent_roster = [dict(row) for row in cursor.fetchall()]
        except Exception:
            pass  # Table may not exist yet

        # Last week's matchup result (for Monday recaps)
        last_week_result = None
        try:
            cursor.execute("""
                SELECT week, my_team_name, opponent_team_name,
                       my_actual_points, opponent_actual_points,
                       my_player_stats
                FROM weekly_matchup_snapshots
                WHERE my_actual_points IS NOT NULL AND my_actual_points > 0
                ORDER BY week DESC LIMIT 1
            """)
            row = cursor.fetchone()
            if row:
                import json as _json

                player_stats = []
                try:
                    player_stats = (
                        _json.loads(row["my_player_stats"]) if row["my_player_stats"] else []
                    )
                except Exception:
                    pass
                last_week_result = {
                    "week": row["week"],
                    "my_team": row["my_team_name"],
                    "opponent": row["opponent_team_name"],
                    "my_points": row["my_actual_points"],
                    "opp_points": row["opponent_actual_points"],
                    "my_player_stats": player_stats,
                }
        except Exception:
            pass

        # Top free agents
        cursor.execute(
            """
            SELECT p.name, p.team, p.position,
                   pp.projected_ros_points, pp.surplus_value, pp.positional_rank
            FROM players p
            JOIN player_points pp ON pp.player_id = p.id
                AND pp.season = ? AND pp.period = 'full_season'
            WHERE p.id NOT IN (SELECT player_id FROM rosters)
                AND pp.projected_ros_points > 0
            ORDER BY pp.projected_ros_points DESC
            LIMIT 50
        """,
            (SEASON,),
        )
        free_agents = [dict(row) for row in cursor.fetchall()]

        # Player name → FanGraphs URL lookup (for linking in reports)
        cursor.execute("""
            SELECT name, fangraphs_id, position FROM players
            WHERE fangraphs_id IS NOT NULL AND fangraphs_id != ''
        """)
        player_links = {}
        pitching_positions = {"SP", "RP", "P"}
        for row in cursor.fetchall():
            name = row["name"]
            fg_id = row["fangraphs_id"]
            positions = set(row["position"].split(",")) if row["position"] else set()
            stats_type = "pitching" if positions & pitching_positions else "batting"
            slug = name.lower().replace(" ", "-").replace(".", "").replace("'", "")
            player_links[name] = (
                f"https://www.fangraphs.com/players/{slug}/{fg_id}/stats/{stats_type}"
            )

        conn.close()

        opp_name = opponent_info["opponent_team_name"] if opponent_info else "Unknown"
        log.info(
            "Loaded league context: %d roster, %d rival, %d opponent (%s), %d free agents, %d standings, %d player links",
            len(my_roster),
            len(rival_roster),
            len(opponent_roster),
            opp_name,
            len(free_agents),
            len(standings),
            len(player_links),
        )

        return {
            "my_roster": my_roster,
            "rival_roster": rival_roster,
            "opponent_info": opponent_info,
            "opponent_roster": opponent_roster,
            "free_agents": free_agents,
            "standings": standings,
            "player_links": player_links,
            "last_week_result": last_week_result,
        }

    except Exception as e:
        log.error("Failed to load league context: %s", e)
        return None


def get_weekly_game_counts() -> dict[str, int]:
    """Get number of games per MLB team for the current week using MLB Stats API."""
    try:
        import statsapi

        today = date.today()
        # Find Monday of current week
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)

        games = statsapi.schedule(
            start_date=monday.strftime("%Y-%m-%d"),
            end_date=sunday.strftime("%Y-%m-%d"),
        )

        counts: dict[str, int] = {}
        for game in games:
            for team_key in ("away_name", "home_name"):
                team = game.get(team_key, "")
                if team:
                    counts[team] = counts.get(team, 0) + 1

        # Map full names to abbreviations
        # statsapi uses full names, we need abbreviations
        TEAM_ABBREV = {
            "Arizona Diamondbacks": "ARI",
            "Atlanta Braves": "ATL",
            "Baltimore Orioles": "BAL",
            "Boston Red Sox": "BOS",
            "Chicago Cubs": "CHC",
            "Chicago White Sox": "CWS",
            "Cincinnati Reds": "CIN",
            "Cleveland Guardians": "CLE",
            "Colorado Rockies": "COL",
            "Detroit Tigers": "DET",
            "Houston Astros": "HOU",
            "Kansas City Royals": "KC",
            "Los Angeles Angels": "LAA",
            "Los Angeles Dodgers": "LAD",
            "Miami Marlins": "MIA",
            "Milwaukee Brewers": "MIL",
            "Minnesota Twins": "MIN",
            "New York Mets": "NYM",
            "New York Yankees": "NYY",
            "Oakland Athletics": "OAK",
            "Philadelphia Phillies": "PHI",
            "Pittsburgh Pirates": "PIT",
            "San Diego Padres": "SD",
            "San Francisco Giants": "SF",
            "Seattle Mariners": "SEA",
            "St. Louis Cardinals": "STL",
            "Tampa Bay Rays": "TB",
            "Texas Rangers": "TEX",
            "Toronto Blue Jays": "TOR",
            "Washington Nationals": "WSH",
        }
        result = {}
        for full_name, count in counts.items():
            abbrev = TEAM_ABBREV.get(full_name, full_name)
            result[abbrev] = count

        log.info("Loaded game counts for %d teams this week", len(result))
        return result

    except Exception as e:
        log.warning("Could not load weekly game counts: %s", e)
        return {}


def load_previous_sentiments() -> dict[str, str]:
    """Load sentiments from the most recent prior roster-intel report.

    Returns {player_name: sentiment} dict, e.g. {"Junior Caminero": "BULLISH"}.
    """
    if not ANALYSIS_DIR.exists():
        return {}

    # Find the most recent roster-intel file that's NOT from today
    today_str = date.today().isoformat()
    for filepath in sorted(ANALYSIS_DIR.glob("*_roster-intel.md"), reverse=True):
        if filepath.name.startswith(today_str):
            continue
        try:
            text = filepath.read_text(encoding="utf-8")
            sentiments = {}
            # Parse ### headers and | Sentiment | rows
            current_player = None
            for line in text.splitlines():
                if line.startswith("### "):
                    # Extract player name from "### [Name](url) (TEAM, POS)" or "### Name (TEAM, POS)"
                    name_match = re.search(
                        r"###\s+(?:\[)?([A-ZÀ-Ý][a-zà-ý]+(?:\s+[A-ZÀ-Ý][a-zà-ý]+)+)", line
                    )
                    if name_match:
                        current_player = name_match.group(1)
                elif current_player and "| Sentiment |" in line:
                    # Extract sentiment value from "| Sentiment | BULLISH |"
                    sent_match = re.search(r"\|\s*Sentiment\s*\|\s*(\w+)", line)
                    if sent_match:
                        sentiments[current_player] = sent_match.group(1)
                        current_player = None

            if sentiments:
                log.info("Loaded %d previous sentiments from %s", len(sentiments), filepath.name)
                return sentiments
        except Exception:
            continue

    return {}


def format_league_context(ctx: dict) -> str:
    """Format league data as text for the prompt."""
    lines = []

    lines.append("## MY ROSTER")
    for p in ctx["my_roster"]:
        pts = p.get("projected_ros_points") or 0
        steamer = p.get("steamer_ros_points") or 0
        surplus = p.get("surplus_value") or 0
        rank = p.get("positional_rank") or "?"
        lines.append(
            f"- {p['name']} ({p['team']}, {p['position']}) "
            f"[Slot: {p['roster_position']}] "
            f"Proj: {pts:.0f} pts | Steamer: {steamer:.0f} | "
            f"Surplus: {surplus:.0f} | Pos Rank: #{rank}"
        )

    # This week's opponent
    opponent_info = ctx.get("opponent_info")
    opponent_roster = ctx.get("opponent_roster", [])
    facing_ithilien = False

    if opponent_info:
        opp_name = opponent_info["opponent_team_name"]
        facing_ithilien = "ithilien" in opp_name.lower()
        my_proj = opponent_info.get("my_projected_points") or 0
        opp_proj = opponent_info.get("opponent_projected_points") or 0

        lines.append(f"\n## THIS WEEK'S H2H OPPONENT: {opp_name}")
        if facing_ithilien:
            lines.append("NOTE: You are facing your brother (Ithilien) this week!")
        lines.append(f"My projected points: {my_proj:.0f}")
        lines.append(f"Opponent projected points: {opp_proj:.0f}")
        if opponent_roster:
            lines.append(f"\n{opp_name}'s Roster:")
            for p in opponent_roster:
                pts = p.get("projected_ros_points") or 0
                lines.append(f"- {p['name']} ({p['team']}, {p['position']}) Proj: {pts:.0f} pts")

    # Ithilien (brother's team) — only if NOT the opponent this week
    if ctx["rival_roster"] and not facing_ithilien:
        lines.append("\n## ITHILIEN'S ROSTER (BROTHER'S TEAM — NOT your opponent this week)")
        for p in ctx["rival_roster"]:
            pts = p.get("projected_ros_points") or 0
            lines.append(f"- {p['name']} ({p['team']}, {p['position']}) Proj: {pts:.0f} pts")
    elif ctx["rival_roster"] and facing_ithilien:
        lines.append("\n## (Ithilien roster shown above as this week's opponent)")

    if ctx["free_agents"]:
        lines.append("\n## TOP FREE AGENTS")
        for p in ctx["free_agents"][:30]:
            pts = p.get("projected_ros_points") or 0
            surplus = p.get("surplus_value") or 0
            rank = p.get("positional_rank") or "?"
            lines.append(
                f"- {p['name']} ({p['team']}, {p['position']}) "
                f"Proj: {pts:.0f} pts | Surplus: {surplus:.0f} | Pos Rank: #{rank}"
            )

    if ctx["standings"]:
        lines.append("\n## STANDINGS")
        for t in ctx["standings"]:
            lines.append(
                f"- #{t['rank']} {t['team_name']} "
                f"({t.get('wins', 0)}-{t.get('losses', 0)}) "
                f"PF: {t.get('points_for', 0):.0f} PA: {t.get('points_against', 0):.0f}"
            )

    # Last week's matchup result (for Monday recaps)
    lwr = ctx.get("last_week_result")
    if lwr and lwr.get("my_points", 0) > 0:
        result = "WIN" if lwr["my_points"] > lwr["opp_points"] else "LOSS"
        lines.append(f"\n## LAST WEEK'S MATCHUP RESULT (Week {lwr['week']})")
        lines.append(
            f"{lwr['my_team']}: {lwr['my_points']:.1f} pts vs {lwr['opponent']}: {lwr['opp_points']:.1f} pts — {result}"
        )
        if lwr.get("my_player_stats"):
            lines.append("\nMy Player Performance (sorted by points):")
            sorted_players = sorted(
                lwr["my_player_stats"], key=lambda p: p.get("points", 0), reverse=True
            )
            for p in sorted_players:
                pts = p.get("points", 0)
                stats = p.get("stats", {})
                pos = p.get("position", "?")
                if pos == "B":
                    stat_line = f"HR:{stats.get('HR', 0):.0f} RBI:{stats.get('RBI', 0):.0f} R:{stats.get('R', 0):.0f} SB:{stats.get('SB', 0):.0f} K:{stats.get('K', 0):.0f}"
                else:
                    stat_line = f"IP:{stats.get('IP', 0):.1f} K:{stats.get('K', 0):.0f} ER:{stats.get('ER', 0):.0f} SV:{stats.get('SV', 0):.0f} HLD:{stats.get('HLD', 0):.0f}"
                lines.append(f"- {p['name']} ({pos}): {pts:.1f} pts | {stat_line}")

    # Games this week
    game_counts = ctx.get("game_counts", {})
    if game_counts:
        lines.append("\n## GAMES THIS WEEK")
        for team, count in sorted(game_counts.items()):
            lines.append(f"- {team}: {count} games")

    lines.append("\n## LEAGUE SCORING")
    lines.append("Batting: R=1, 1B=1, 2B=2, 3B=3, HR=4, RBI=1, SB=2, CS=-1, BB=1, HBP=1, K=-0.5")
    lines.append(
        "Pitching: OUT=1.5, K=0.5, SV=7, HLD=4, RW=4, QS=2, ER=-4, BB(P)=-0.75, H(P)=-0.75"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = (
    "You are a professional fantasy baseball analyst writing a daily intelligence "
    "report in the style of ESPN or The Athletic. Write with authority and "
    "analytical depth — be specific with numbers and projected points. "
    "Focus on actionable insights. Be thorough — this report is the reader's "
    "primary daily briefing and should be comprehensive, not abbreviated. "
    "This is a 10-team H2H Points keeper league. "
    "\n\nFORMATTING RULES:\n"
    "- Use ## for section headers, ### for player names within sections\n"
    "- Use normal text weight for most content. Only use **bold** sparingly "
    "for key terms like sentiment tags (BULLISH, BEARISH) or action labels "
    "(PRIORITY ADD, SELL HIGH). Do NOT bold entire sentences or paragraphs.\n"
    "- Use bullet lists for supporting points under each player/topic\n"
    "- Use *italics* for source citations\n"
    "- Write in a conversational, analytical tone — not a bullet-point dump\n"
    "\nCONTENT RULES:\n"
    "- When citing expert opinions, always note the source name and date in italics\n"
    "- When content is more than 48 hours old, note it may be stale\n"
    "- Match player names flexibly — 'Bobby Witt' and 'Bobby Witt Jr.' are the same player\n"
    "- CRITICAL: Only recommend START/SIT for players on MY ROSTER. Do not tell me to "
    "start players I don't own. If a player is on another team, that's a TRADE TARGET, not a start.\n"
    "- The reader is a Cardinals fan — make the Cardinals Corner section insightful\n"
    "- The reader's brother runs 'Ithilien' — keep the rivalry section brief and factual\n"
    "- ALWAYS use a player's full first and last name — never just a last name. "
    "Write 'Yusei Kikuchi' not 'Kikuchi'. This is required for player linking.\n"
    "- DO NOT be lazy or brief. Each section should have real substance and deep analysis."
)


SECTION_INSTRUCTIONS = {
    "last-week-recap": """## Last Week's Recap
Using the LAST WEEK'S MATCHUP RESULT and STANDINGS data provided:

### League Standings
Format the standings as a markdown table with columns: Rank, Team, Record (W-L), PF, PA. Highlight my team's position.

### Matchup Result
Show my score vs opponent's score. Note the win or loss and margin. Identify my top 3 and bottom 3 performers by points scored.

### My Roster Performance
List every player on my roster sorted by points scored (highest first). For each, show: name, position, points, and 2-3 key stats (HR, RBI, SB for hitters; IP, K, ER for pitchers). Flag any players who significantly over- or under-performed their projection.""",
    "roster-intel": """## My Roster Intel
Go through EVERY player on MY ROSTER ONLY, ordered by urgency (sell highs and bearish players at the top; neutral/not-mentioned players at the bottom). Do NOT include free agents or waiver targets — those belong in the Waiver Targets section.

For each player use this EXACT format:

### Player Name (TEAM, POS)

| | |
|---|---|
| Sentiment | BULLISH / BEARISH / NEUTRAL / NOT MENTIONED |
| Lineup | START / SIT / MONITOR / SELL HIGH / DROP / STASH (IL) |
| Confidence | HIGH (X sources) / MEDIUM (X sources) / LOW (1 source) / NONE |
| Games This Week | Use the GAMES THIS WEEK data provided |
| Trend | Use PREVIOUS SENTIMENTS data if available, otherwise "— (first report)" |

If mentioned in expert content: write a substantive paragraph of analysis — what experts said, the context, source citations in italics, and what it means for fantasy value. Include projection numbers when relevant.
If NOT mentioned in any expert content: write "Not mentioned in recent expert content." and move to the next player. Do not fabricate analysis.

Confidence ratings: HIGH = 3+ distinct sources mentioned this player, MEDIUM = 2 sources, LOW = 1 source, NONE = not mentioned.
Trend: Compare against PREVIOUS SENTIMENTS data. Format as "PREVIOUS → CURRENT ↑" or "PREVIOUS → CURRENT ↓" or "CURRENT (unchanged)" or "— (first report)" if no previous data.

Do not skip any player on my roster.""",
    "matchup-preview": """## Matchup Preview
IMPORTANT: Analyze the matchup against THIS WEEK'S H2H OPPONENT as identified in the league data above. Do NOT confuse the opponent with Ithilien (brother's team) — they are separate unless the data explicitly says you are facing Ithilien this week.
Write this section like a sports preview column with narrative paragraphs, not just bullets:
- Name the opponent team clearly at the start
- Compare team strengths and weaknesses position-by-position using projection data
- Identify the projected point edge or deficit
- Call out 3-4 key players on each side who could swing the matchup
- Discuss league standings context — what's at stake, playoff implications
- Identify the matchup's most volatile positions (where the swing is biggest)
Write at least 3 substantial paragraphs.""",
    "waiver-intel": """## Waiver Targets
Cross-reference expert-mentioned players with the free agents list. For each target write a mini-analysis:

### Player Name (TEAM, POS) — PRIORITY ADD / SPECULATIVE ADD / WATCHLIST
Projection: X pts ROS, #Y at position
Expert take: what was said, by whom, when. Write 2-3 sentences of context.
Why it matters for my team: how they'd fit my roster.

Identify at least 5 targets. Flag closers (SV=7) and setup men (HLD=4) — these are premium in this scoring system. Players mentioned by multiple sources should be prioritized.""",
    "trade-intel": """## Trade Signals
Write substantive analysis for each signal — not just names and labels.

### Sell High Candidates (My Roster)
For each: who the player is, what experts are saying that concerns you, their current projection, what kind of return I should target, and a specific trade partner suggestion from the league.

### Buy Low Targets (Other Teams)
For each: who owns them, why experts are higher than projections, the catalyst, and what I might offer from my roster.

At least 3 players across the sell high and buy low categories with real analysis for each. Do NOT include Ithilien trade targets here — those belong in the Sibling Rivalry section.""",
    "projection-watch": """## Projection Watch
Focus exclusively on MY ROSTERED PLAYERS where expert opinion diverges from Steamer/consensus projections. Projection disagreements for waiver or trade targets are covered in those sections.
- For each disagreement: name the player, the expert projection vs consensus, the specific stat gap, and why it matters
- Flag projection-changing news for my players: injuries, role changes, lineup moves, spring results
- Note where Steamer is significantly higher or lower than the composite for my players
- Call out which disagreements I should act on (sell high? hold? buy more?)
At least 3 specific, detailed disagreements for my rostered players.""",
    "around-the-league": """## Around the League
A comprehensive summary of everything discussed across all expert content that doesn't fit neatly into the sections above. This is the "big picture" view:
- Major news and storylines from the expert content
- Trends across the industry (what are multiple experts agreeing/disagreeing on?)
- Notable draft strategy shifts or ADP movers discussed
- Prospect call-up timelines or roster battles mentioned
- Any meta-analysis (e.g., how different projection systems are approaching the new season)
Write this as an engaging narrative — this section should capture everything interesting from the expert content even if it's not directly about my team.""",
    "cardinals-corner": """## Cardinals Corner
All Cardinals-relevant news and analysis from expert content:
- Any STL players discussed (what was said, by whom, full context)
- STL players on my roster, opponent's team, or Ithilien's team — fantasy implications
- Cardinals organizational news: roster moves, prospect timelines, rotation decisions
- Spring training observations about Cardinals players
If minimal Cardinals content, note that and mention any Cardinals-adjacent news.""",
    "sibling-rivalry": """## Sibling Rivalry
All analysis about Ithilien (brother's team) goes here. Cover:
- His current standing, record, and trajectory in the league
- Expert mentions of his key players — positive or negative sentiment
- Trade leverage: which of his players are underperforming vs projections? Which are overperforming?
- Specific trade targets: which of his players should I try to buy low on? Which of my players might appeal to him?
- Suggest 1-2 specific trade packages with reasoning
Brief and factual, but with actionable intelligence.""",
    "injury-watch": """## Injury Watch
List ONLY my rostered players who have injury concerns mentioned in the expert content. For each:

### Player Name (TEAM, POS)
**Status:** IL / DTD / OUT X weeks / Questionable — brief description of injury
*Source citation, date*
**Impact:** 2-3 sentences on fantasy impact — timeline, replacement options, whether to hold or drop.""",
    "action-items": """## Action Items
A clean markdown checklist summarizing every actionable recommendation from this report. Use this exact format:

- [ ] **PRIORITY ADD**: Player Name (TEAM, POS) — brief action (e.g., "drop Robert Suarez to make room")
- [ ] **SELL HIGH**: Player Name — brief action (e.g., "trade before Week 1, target mid-tier OF")
- [ ] **MONITOR**: Player Name — what to watch for (e.g., "velocity in first 2 appearances")
- [ ] **DROP**: Player Name — reasoning
- [ ] **IL STASH**: Player Name — timeline note

Include every player with a non-START/non-NEUTRAL action from the Roster Intel section, plus any waiver and trade recommendations. Order by urgency. This should be copy-paste ready for a to-do list.""",
}


def build_prompt(
    content_context: str,
    league_context: str | None,
    today: date,
    mode: str = "weekly",
) -> str:
    """Build the user message for the intel report.

    mode="daily" — lightweight briefing (Key Takeaways, Roster Intel, Around the League)
    mode="weekly" — full comprehensive report (all 10 sections)
    """
    is_monday = today.weekday() == 0

    if mode == "daily":
        sections_to_include = MONDAY_SECTIONS if is_monday else DAILY_SECTIONS
        report_label = "Monday recap and daily briefing" if is_monday else "daily briefing"
    else:
        sections_to_include = WEEKLY_SECTIONS
        report_label = "comprehensive weekly intelligence report"

    section_text = "\n\n".join(
        SECTION_INSTRUCTIONS[s] for s in sections_to_include if s in SECTION_INSTRUCTIONS
    )

    instructions = f"""Write a {report_label} for {today.strftime("%B %d, %Y")}.

Use exactly these section headers (## level) in this order. Be thorough and analytical in EVERY section — write like a columnist, not a summary bot. Do NOT include [[toc-levels:2]] or any table of contents marker — that is handled separately.

{section_text}
"""

    parts = [instructions]

    if league_context:
        parts.append(f"\n---\n\n# LEAGUE DATA\n\n{league_context}")
    else:
        parts.append(
            "\n---\n\nNote: No league data available yet. Provide general expert analysis "
            "and trending player insights suitable for a standard 10-team H2H Points league."
        )

    # Previous sentiments for trend tracking
    prev_sentiments = load_previous_sentiments()
    if prev_sentiments:
        parts.append("\n---\n\n# PREVIOUS SENTIMENTS (from last report)\n")
        for name, sent in sorted(prev_sentiments.items()):
            parts.append(f"- {name}: {sent}")
        parts.append("")
    else:
        parts.append(
            "\n---\n\nNo previous report available — use '— (first report)' for all Trend values.\n"
        )

    parts.append(f"\n---\n\n# EXPERT CONTENT\n\n{content_context}")

    return "".join(parts)


# ---------------------------------------------------------------------------
# Report generation and splitting
# ---------------------------------------------------------------------------


def generate_intel(
    content_items: list[dict],
    league_ctx: dict | None,
    today: date,
    mode: str = "weekly",
    dry_run: bool = False,
) -> tuple[str | None, int, int]:
    """Generate the intel report via a single Claude API call.

    mode="daily" — lightweight (3 sections, ~$0.15-0.25)
    mode="weekly" — full comprehensive (10 sections, ~$0.50-1.00)

    Returns (report_text, input_tokens, output_tokens).
    """
    content_context = build_content_context(content_items)
    league_context = format_league_context(league_ctx) if league_ctx else None

    user_message = build_prompt(content_context, league_context, today, mode=mode)

    if dry_run:
        log.info("=== DRY RUN ===")
        log.info("System prompt (%d chars):\n%s", len(SYSTEM_PROMPT), SYSTEM_PROMPT[:500])
        log.info(
            "User message (%d chars, ~%d tokens):\n%s...",
            len(user_message),
            len(user_message) // 4,
            user_message[:1000],
        )
        return None, 0, 0

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY not set in .env")
        return None, 0, 0

    log.info("Generating comprehensive daily intel report...")

    client = anthropic.Anthropic(api_key=api_key)

    # Retry with backoff for rate limits
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=16000 if mode == "weekly" else 8000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            text = response.content[0].text
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens

            log.info(
                "Generated: %d words, %d input tokens, %d output tokens",
                len(text.split()),
                input_tokens,
                output_tokens,
            )
            return text, input_tokens, output_tokens

        except anthropic.RateLimitError:
            import time

            wait = 60 * (attempt + 1)
            if attempt < max_retries - 1:
                log.warning(
                    "Rate limited. Waiting %ds before retry %d/%d...",
                    wait,
                    attempt + 2,
                    max_retries,
                )
                time.sleep(wait)
            else:
                log.error("Rate limit exceeded after %d retries", max_retries)
                return None, 0, 0

        except Exception as e:
            log.error("Failed to generate intel: %s", e)
            return None, 0, 0

    return None, 0, 0


def linkify_players(text: str, player_links: dict[str, str]) -> str:
    """Replace player names with FanGraphs markdown links.

    Two passes:
    1. Always link names in ### headers (these are player entry points)
    2. Link first occurrence in body text for any remaining unlinked names

    Sorts longest names first to avoid partial matches.
    """
    sorted_names = sorted(player_links.keys(), key=len, reverse=True)

    # Pass 1: Link all ### headers
    for name in sorted_names:
        url = player_links[name]
        # Match name in ### header that isn't already linked
        header_pattern = rf"(###\s+)(?<!\[)({re.escape(name)})(?!\]\()"
        text = re.sub(header_pattern, rf"\1[{name}]({url})", text)

    # Pass 2: Link first body occurrence of each name (skip already-linked)
    linked = set()
    for name in sorted_names:
        if name in linked:
            continue
        url = player_links[name]
        pattern = rf"(?<!\[)({re.escape(name)})(?!\]\()"
        match = re.search(pattern, text)
        if match:
            text = text[: match.start()] + f"[{match.group(1)}]({url})" + text[match.end() :]
            linked.add(name)

    return text


def linkify_sources(text: str, content_items: list[dict]) -> str:
    """Replace source citations like *Pitcher List, Mar 23* with links to the original URL.

    Builds a lookup from content items using source_name + date,
    then finds italicized citations and wraps them in links.
    """
    # Build lookup: "Source Name, Mon DD" → url
    source_lookup = {}
    for item in content_items:
        if not item.get("url"):
            continue
        date_str = item["date_parsed"].strftime("%b %d")  # e.g., "Mar 23"
        # Try both with and without year
        key = f"{item['source_name']}, {date_str}"
        source_lookup[key] = item["url"]
        # Also try short date like "Mar 23"
        date_short = item["date_parsed"].strftime("%b %-d")  # e.g., "Mar 3" vs "Mar 03"
        if date_short != date_str:
            source_lookup[f"{item['source_name']}, {date_short}"] = item["url"]

    # Sort by key length descending to avoid partial matches
    for citation, url in sorted(source_lookup.items(), key=lambda x: len(x[0]), reverse=True):
        # Match *citation* that isn't already linked
        pattern = rf"(?<!\[)\*({re.escape(citation)})\*(?!\]\()"
        match = re.search(pattern, text)
        if match:
            text = text[: match.start()] + f"[*{match.group(1)}*]({url})" + text[match.end() :]

    return text


def split_into_sections(full_text: str) -> dict[str, str]:
    """Split the combined report into individual sections by ## headers.

    Returns dict mapping section slug to section content (including its header).
    """
    result = {}

    # Split on ## headers
    parts = re.split(r"(?=^## )", full_text, flags=re.MULTILINE)

    for part in parts:
        part = part.strip()
        if not part.startswith("## "):
            continue

        # Extract header text
        header_line = part.split("\n", 1)[0]
        header_text = header_line.lstrip("# ").strip()

        # Match to known sections
        for slug, expected_title in SECTIONS.items():
            if expected_title.lower() in header_text.lower():
                result[slug] = part
                break

    log.info("Split report into %d sections: %s", len(result), list(result.keys()))
    return result


def write_reports(
    today: date,
    full_text: str,
    content_items: list[dict],
    input_tokens: int,
    output_tokens: int,
    report_slug: str = "daily-intel",
    player_links: dict[str, str] | None = None,
) -> list[Path]:
    """Write the full report and individual section files.

    Runs linkify_players and linkify_sources on each section independently
    so every section gets its own first-occurrence links.
    """
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    written = []

    dates = [item["date_parsed"] for item in content_items]
    date_range = (
        f"{min(dates).strftime('%Y-%m-%d')} to {max(dates).strftime('%Y-%m-%d')}"
        if dates
        else today.isoformat()
    )

    sources_section = build_sources_section(content_items)

    # Split into sections first
    sections = split_into_sections(full_text)

    # Linkify each section independently
    linked_sections = {}
    for slug, section_text in sections.items():
        linked = section_text
        if player_links:
            linked = linkify_players(linked, player_links)
        linked = linkify_sources(linked, content_items)
        linked_sections[slug] = linked

    if player_links:
        log.info("Linked player names and sources per-section")

    # Reassemble the full report from linked sections
    linked_full_text = "\n\n".join(linked_sections.values())

    is_weekly = report_slug == "weekly-intel"
    title_prefix = "Weekly Intel" if is_weekly else "Daily Intel"
    title = f"{title_prefix} — {today.strftime('%B %d, %Y')}"
    full_frontmatter = f"""---
title: "{title}"
type: {report_slug}
date: {today.isoformat()}
generated_at: {datetime.now(timezone.utc).isoformat()}
model: {MODEL}
input_tokens: {input_tokens}
output_tokens: {output_tokens}
source_count: {len(content_items)}
content_date_range: "{date_range}"
---"""

    full_content = (
        f"{full_frontmatter}\n\n# {title}\n\n"
        f"*All podcast and blog resources are at the end of this document*\n\n"
        f"<!-- omit from toc -->\n"
        f"## Contents:\n\n"
        f"[[toc]]\n"
        f"[[toc-levels:2]]\n"
        f"[[no-header]]\n\n"
        f"{linked_full_text}\n\n"
        f"---\n\n{sources_section}\n"
    )
    full_path = ANALYSIS_DIR / f"{today.isoformat()}_{report_slug}.md"
    full_path.write_text(full_content, encoding="utf-8")
    written.append(full_path)
    log.info("  Wrote: %s", full_path.name)

    # Write individual section files
    for slug, section_text in linked_sections.items():
        section_title = SECTIONS.get(slug, slug.replace("-", " ").title())
        section_frontmatter = f"""---
title: "{section_title} — {today.strftime("%B %d, %Y")}"
type: {slug}
date: {today.isoformat()}
parent: {today.isoformat()}_{report_slug}.md
generated_at: {datetime.now(timezone.utc).isoformat()}
---"""

        section_content = f"{section_frontmatter}\n\n# {section_title}\n\n{section_text}\n"
        section_path = ANALYSIS_DIR / f"{today.isoformat()}_{slug}.md"
        section_path.write_text(section_content, encoding="utf-8")
        written.append(section_path)
        log.info("  Wrote: %s", section_path.name)

    return written


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(
    mode: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    days: int | None = None,
) -> None:
    """Generate the intel report.

    Schedule (auto when mode is None):
      - Saturday: full weekly report (all 10 sections, past 7 days of content)
      - Other days: lightweight daily briefing (3 sections, new content only)

    Content window:
      - Weekly runs: past WEEKLY_CONTENT_DAYS (default 7) of content
      - Daily runs: only content since last report
      - --days N: override the content window to N days
    """
    today = date.today()
    is_weekly_day = today.weekday() == WEEKLY_DAY

    # Determine mode
    if mode is None:
        mode = "weekly" if is_weekly_day else "daily"

    report_slug = "weekly-intel" if mode == "weekly" else "daily-intel"
    max_tokens = 16000 if mode == "weekly" else 8000

    # Check if today's report already exists
    full_path = ANALYSIS_DIR / f"{today.isoformat()}_{report_slug}.md"
    if full_path.exists() and not force and not dry_run:
        log.info("Today's %s report already exists (use --force to regenerate)", mode)
        return

    # Determine content window
    if days is not None:
        # Explicit --days override
        since = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) - timedelta(
            days=days
        )
        log.info("Loading content since %s (--days %d)", since.strftime("%Y-%m-%d"), days)
        content_items = load_recent_content(since=since)
    elif mode == "weekly" or force:
        # Weekly gets past N days of content (not all-time — avoids blowing context limit)
        since = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) - timedelta(
            days=WEEKLY_CONTENT_DAYS
        )
        log.info("Loading content since %s for %s report", since.strftime("%Y-%m-%d"), mode)
        content_items = load_recent_content(since=since)
    else:
        # Daily gets only new content since last report
        last_report = get_last_report_time()
        if last_report:
            log.info(
                "Last report: %s — loading new content since then",
                last_report.strftime("%Y-%m-%d %H:%M"),
            )
            content_items = load_recent_content(since=last_report)
        else:
            log.info("No previous report — loading all available content")
            content_items = load_recent_content(since=None)

    if not content_items:
        log.warning("No new content to analyze.")
        return

    log.info(
        "Mode: %s | %d content items | %s",
        mode.upper(),
        len(content_items),
        "Saturday full report" if mode == "weekly" else "lightweight briefing",
    )

    # Load league context
    league_ctx = load_league_context(DB_PATH)
    if league_ctx:
        # Add weekly game counts
        league_ctx["game_counts"] = get_weekly_game_counts()
        log.info("League context loaded")
    else:
        log.info("No league data — content-only report")

    # Single API call
    text, input_tokens, output_tokens = generate_intel(
        content_items, league_ctx, today, mode=mode, dry_run=dry_run
    )

    if text:
        player_links = league_ctx.get("player_links", {}) if league_ctx else {}

        paths = write_reports(
            today,
            text,
            content_items,
            input_tokens,
            output_tokens,
            report_slug=report_slug,
            player_links=player_links,
        )

        # Cost estimate (Opus: $5/M input, $25/M output)
        cost = (input_tokens * 5 + output_tokens * 25) / 1_000_000
        log.info(
            "Done. Wrote %d files. Tokens: %d in / %d out (~$%.2f)",
            len(paths),
            input_tokens,
            output_tokens,
            cost,
        )
    else:
        log.error(
            "No report generated — Claude API returned empty response. "
            "Check API key, rate limits, and network connectivity."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate fantasy baseball intelligence report")
    parser.add_argument(
        "--mode",
        choices=["daily", "weekly"],
        default=None,
        help="Report mode (default: auto — weekly on Saturdays, daily otherwise)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print prompt without calling Claude API",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if today's report already exists",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Content window in days (default: 7 for weekly, since-last-report for daily)",
    )
    args = parser.parse_args()

    run(
        mode=args.mode,
        dry_run=args.dry_run,
        force=args.force,
        days=args.days,
    )


if __name__ == "__main__":
    main()
