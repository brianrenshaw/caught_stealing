#!/usr/bin/env python3
"""Daily St. Louis Cardinals intelligence report.

Sibling to scripts.daily_analysis but scoped to Cardinals-only content
(Locked On Cardinals podcast, Viva El Birdos, Redbird Rants, The Cardinal
Nation) plus postgame Statcast data via app.services.cardinals_postgame.

Generates a single markdown at data/content/analysis/{today}_cardinals-daily.md
with four sections: Previous Game, MLB Cardinals, Minor League Cardinals,
Fan Takeaway. Uses Opus 4.7 via the Max-subscription claude -p path.

Usage:
    uv run python -m scripts.cardinals_daily_report                # generate today's
    uv run python -m scripts.cardinals_daily_report --force        # regenerate even if exists
    uv run python -m scripts.cardinals_daily_report --dry-run      # preview prompt, no API call
    uv run python -m scripts.cardinals_daily_report --days 14      # content window override
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import feedparser
import httpx
from dotenv import load_dotenv

# Reuse battle-tested helpers from the fantasy report
from scripts.daily_analysis import (
    MAX_CONTENT_CHARS,
    _invoke_claude_cli,
    linkify_players,
    parse_frontmatter,
)
from app.services.cardinals_postgame import get_cardinals_postgame

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

MODEL = "claude-opus-4-7"
USE_CLAUDE_CLI = os.getenv("DAILY_ANALYSIS_USE_CLI", "1") == "1"
CONTENT_WINDOW_DAYS = 5
REPORT_SLUG = "cardinals-daily"

# Feed keys (matched against the {date}_{key}_*.md filename prefix)
CARDINALS_SOURCES: set[str] = {
    "viva_el_birdos",
    "redbird_rants",
    "cardinal_nation",
    "locked_on_cardinals",
    "walton_and_reis",
}

# MLB-wide headlines feeds used by the "Around the League" section
MLB_NEWS_FEEDS: list[tuple[str, str]] = [
    ("ESPN MLB", "https://www.espn.com/espn/rss/mlb/news"),
    ("MLB.com", "https://www.mlb.com/feeds/news/rss.xml"),
]

# Feeds for the closing "Interesting Analysis" section. We pull headlines + summaries
# from every non-Cardinals feed we already use elsewhere (blogs + fantasy podcast
# episode descriptions) PLUS dedicated baseball-analysis feeds. The model is
# instructed at prompt time to filter STRICTLY for general baseball analysis:
# skip pure fantasy content (draft, projections, waiver wire, start/sit) and skip
# Cardinals-specific items (they have their own section earlier).
ANALYSIS_FEEDS: list[tuple[str, str]] = [
    # Mixed analysis + fantasy — model filters
    ("FanGraphs", "https://blogs.fangraphs.com/feed/"),
    ("Pitcher List", "https://pitcherlist.com/feed"),
    ("RotoWire", "https://www.rotowire.com/rss/news.php?sport=MLB"),
    # Mostly fantasy podcast episodes, occasional non-fantasy deep dives
    ("CBS Fantasy Baseball", "https://feeds.megaphone.fm/CBS6735868419"),
    ("FantasyPros Baseball",
     "https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/"
     "03db435f-86aa-4395-95a3-b2d70144b868/a32aaa57-276f-4ebd-af98-b2d70144b87c/podcast.rss"),
    ("Locked On Fantasy Baseball", "https://pdrl.fm/72f472/feeds.simplecast.com/4vzt_3en"),
    ("In This League", "https://www.spreaker.com/show/3691391/episodes/feed"),
    # Pure baseball analysis — typically the best source for this section
    ("Effectively Wild", "https://blogs.fangraphs.com/feed/effectively-wild/"),
    ("FanGraphs Audio", "https://blogs.fangraphs.com/feed/podcast/"),
]

# Blot.im Dropbox sync folder. Posts dropped here publish via Blot's Dropbox watcher.
BLOT_POSTS_DIR = Path(
    "/Users/brianrenshaw/Library/CloudStorage/"
    "Dropbox-Brianrenshawmedia/Brian Renshaw/Apps/Blot/Posts"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Content loading (Cardinals-only, by source key in filename)
# ---------------------------------------------------------------------------


def _matches_cardinals(filename: str) -> bool:
    """Return True if a content filename starts with a Cardinals source key.

    Convention from blog_ingest/podcast_transcriber:
      {YYYY-MM-DD}_{source_key}_{slug}.md
    """
    parts = filename.split("_", 1)
    if len(parts) < 2:
        return False
    rest = parts[1]
    for key in CARDINALS_SOURCES:
        if rest.startswith(key + "_"):
            return True
    return False


def load_cardinals_content(days: int) -> list[dict]:
    """Load Cardinals blog/transcript markdowns from the last `days` days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items: list[dict] = []

    for content_dir, content_type in [(BLOGS_DIR, "blog"), (TRANSCRIPTS_DIR, "transcript")]:
        if not content_dir.exists():
            continue
        for fp in sorted(content_dir.glob("*.md"), reverse=True):
            if not _matches_cardinals(fp.name):
                continue
            try:
                text = fp.read_text(encoding="utf-8")
                meta, body = parse_frontmatter(text)
                date_str = meta.get("date", "")
                if not date_str:
                    continue
                try:
                    pub = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if pub < cutoff:
                    continue
                items.append({
                    "title": meta.get("title", fp.stem),
                    "source_name": meta.get("source_name", meta.get("source", "Unknown")),
                    "url": meta.get("url", ""),
                    "date": date_str,
                    "date_parsed": pub,
                    "content": body,
                    "type": content_type,
                    "filename": fp.name,
                    "word_count": len(body.split()),
                })
            except Exception as e:
                log.warning("Failed to read %s: %s", fp.name, e)

    items.sort(key=lambda x: x["date_parsed"], reverse=True)
    log.info(
        "Loaded %d Cardinals items (%d blogs, %d transcripts) over %d days",
        len(items),
        sum(1 for i in items if i["type"] == "blog"),
        sum(1 for i in items if i["type"] == "transcript"),
        days,
    )
    return items


def fetch_analysis_headlines(hours: int = 72, max_items: int = 40) -> list[dict]:
    """Pull recent items from baseball-analysis + (mixed) fantasy feeds.

    Headlines + summaries + links only — no audio download or transcription.
    The Cardinals report prompt filters these at write-time to a clean
    'Interesting Analysis' section (non-fantasy, non-Cardinals deep dives).
    """
    return _fetch_rss_headlines(ANALYSIS_FEEDS, hours, max_items)


def _fetch_rss_headlines(
    feeds: list[tuple[str, str]], hours: int, max_items: int
) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items: list[dict] = []
    seen_titles: set[str] = set()

    for source_name, url in feeds:
        try:
            resp = httpx.get(url, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            log.warning("RSS fetch failed for %s: %s", source_name, e)
            continue
        parsed = feedparser.parse(resp.text)
        for entry in parsed.entries:
            title = (entry.get("title") or "").strip()
            if not title or title.lower() in seen_titles:
                continue
            pub = entry.get("published_parsed") or entry.get("updated_parsed")
            pub_dt: datetime | None = None
            if pub:
                try:
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    pub_dt = None
            if pub_dt and pub_dt < cutoff:
                continue
            summary = (entry.get("summary") or "").strip()
            summary = re.sub(r"<[^>]+>", "", summary)
            items.append({
                "title": title,
                "summary": summary[:400],
                "source": source_name,
                "url": entry.get("link", ""),
                "published": pub_dt.isoformat() if pub_dt else None,
            })
            seen_titles.add(title.lower())

    items.sort(key=lambda x: x.get("published") or "", reverse=True)
    return items[:max_items]


def fetch_mlb_news_headlines(hours: int = 24, max_items: int = 25) -> list[dict]:
    """Fetch recent MLB-wide headlines from ESPN MLB + MLB.com RSS feeds.

    Returns up to `max_items` entries published within the last `hours`,
    deduplicated by title, sorted by published-time descending. The model
    is responsible for filtering to baseball-action items in the prompt;
    here we just deliver the raw stream.
    """
    return _fetch_rss_headlines(MLB_NEWS_FEEDS, hours, max_items)


def build_content_block(items: list[dict]) -> str:
    """Concatenate Cardinals content under a hard char budget. Truncate longest first."""
    if not items:
        return "(No Cardinals content found in the lookback window.)"

    blocks: list[tuple[int, str]] = []  # (size, formatted)
    total = 0
    # Newest first; format consistent with daily_analysis
    for item in items:
        header = (
            f"### [{item['type'].title()}] \"{item['title']}\" — {item['source_name']}"
            f" ({item['date'][:10]})\n"
        )
        if item.get("url"):
            header += f"_Source: {item['url']}_\n\n"
        else:
            header += "\n"
        block = header + item["content"].strip() + "\n\n---\n\n"
        blocks.append((len(block), block))

    # Truncate longest items if over budget (typically transcripts)
    if sum(s for s, _ in blocks) > MAX_CONTENT_CHARS:
        # Repeatedly trim the largest until under budget
        while sum(s for s, _ in blocks) > MAX_CONTENT_CHARS and blocks:
            i = max(range(len(blocks)), key=lambda j: blocks[j][0])
            old_size, old_block = blocks[i]
            keep = max(2000, old_size - 4000)
            new_block = old_block[:keep] + "\n…[truncated for length]\n\n---\n\n"
            blocks[i] = (len(new_block), new_block)

    return "".join(b for _, b in blocks)


def build_sources_section(items: list[dict]) -> str:
    """Footer section listing the actual sources fed to Claude."""
    if not items:
        return ""
    lines = ["## Sources Analyzed\n"]
    for item in items:
        date_short = item["date"][:10]
        url = item.get("url", "")
        title = item["title"]
        if url:
            lines.append(f"- [{title}]({url}) — *{item['source_name']}* ({date_short})")
        else:
            lines.append(f"- {title} — *{item['source_name']}* ({date_short})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Player linking (Cardinals roster + recent appearances)
# ---------------------------------------------------------------------------


def load_player_links() -> dict[str, str]:
    """Build player name → FanGraphs URL map.

    Same approach as daily_analysis.load_league_context but standalone since
    we don't need full league context for the Cardinals report.
    """
    links: dict[str, str] = {}
    if not DB_PATH.exists():
        return links
    pitching = {"SP", "RP", "P"}
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT p.name, p.fangraphs_id, p.position,
                   EXISTS (SELECT 1 FROM rosters r WHERE r.player_id = p.id) AS on_roster
            FROM players p
            WHERE p.fangraphs_id IS NOT NULL AND p.fangraphs_id != ''
            ORDER BY on_roster ASC
            """
        )
        for row in cur:
            name = row["name"]
            fg_id = row["fangraphs_id"]
            positions = set((row["position"] or "").split(","))
            stat_type = "pitching" if positions & pitching else "batting"
            slug = name.lower().replace(" ", "-").replace(".", "").replace("'", "")
            links[name] = f"https://www.fangraphs.com/players/{slug}/{fg_id}/stats/{stat_type}"
        conn.close()
    except Exception as e:
        log.warning("Could not load player_links: %s", e)
    return links


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = (
    "You are a St. Louis Cardinals beat writer in the Bernie Miklasz / Derrick Goold tradition — "
    "stat-driven, knowledgeable about the 26-man roster, the bullpen, the rotation, and the farm system. "
    "Write in **THIRD PERSON** about the Cardinals: 'the Cardinals', 'St. Louis', 'their rotation', "
    "'the Cardinals' prospect pipeline'. NEVER use 'I', 'me', 'we', 'us', 'our'. The reader is a fan; "
    "the writer is a reporter. Stat-driven authority — every claim ties to a specific number, expert "
    "quote, or game outcome. No glib hot takes; no fan-rant first person.\n\n"
    "FORMATTING:\n"
    "- ## for section headers, ### for player names or sub-beats\n"
    "- Bold sparingly for tags or key facts (**W**, **L**, **HR**, **IL**)\n"
    "- *Italics* for source citations: *(Locked On Cardinals, May 9)*\n"
    "- Box-score data goes in markdown tables, not prose, in the Previous Game section\n"
    "- Bullet lists under sub-beats; bigger context as flowing prose\n\n"
    "CONTENT RULES:\n"
    "- Lead with concrete numbers from the POSTGAME DATA when present (final score, top hitter, "
    "max exit velocity, top pitch velocity). Don't bury the lede.\n"
    "- Source-citation policy by section:\n"
    "  * **Score and Data section**: NEVER cite blogs, podcasts, or beat writers by name. The game "
    "    narrative runs on POSTGAME DATA only — scoring plays, WPA leaders, top performers, "
    "    Statcast highlights, game context. No 'according to Viva El Birdos' / 'per Locked On "
    "    Cardinals' / etc. in this section.\n"
    "  * **Cardinals Notebook**: cite expert content (blog/podcast) by source name + date when "
    "    drawing on opinions, scouting reports, or roster-decision analysis. Format: *(Locked On "
    "    Cardinals, May 9)*. This is where source attribution lives.\n"
    "  * **Beat Writer's Verdict**: synthesize without name-dropping sources — your voice as the "
    "    beat writer, informed by what you've absorbed.\n"
    "- When citing a podcast, use the podcast title (e.g., *Locked On Cardinals*).\n"
    "- ALWAYS use full first and last names for players (e.g., 'Jordan Walker' not 'Walker') — "
    "required for the FanGraphs linker.\n"
    "- When comparing two numerical values, verify the inequality direction before stating it.\n"
    "- DO NOT INVENT GAME STATE. The series score, standings, won-loss record, and game results "
    "must come from the POSTGAME DATA block or the cited expert content. If the series score is not "
    "explicitly given, do not state one. NEVER hallucinate a record like '23-16' or 'series tied 2-2' "
    "without a direct source. Better to omit a stat than to invent one.\n"
    "- Do NOT invent expert quotes. If a fact isn't in the provided content or postgame data, do "
    "not cite a source for it.\n"
    "- Each major news item (a specific injury, a transaction, a roster decision) lives in detail "
    "in ONE section; cross-reference if it surfaces elsewhere.\n"
    "- Write polished prose — no stream-of-consciousness self-corrections.\n"
    "- DO NOT be lazy or brief. Each section earns its space.\n"
)


SECTION_INSTRUCTIONS = (
    """## Score and Data for {Month D, YYYY}

REPLACE `{Month D, YYYY}` with the actual game date from POSTGAME DATA's `date` field, formatted as e.g. `May 9, 2026`. Your literal `##` heading should read: `## Score and Data for May 9, 2026`. If POSTGAME DATA is null, use today's date and append "(no game)": `## Score and Data for May 10, 2026 (no game)`.

Lead the report with this. Build the section in **this exact order**:

**(a) Header line.** One bold line stating the matchup, result, venue, and pitcher decisions. End the line with a small markdown link to the Baseball Savant game feed (pulled verbatim from POSTGAME DATA's `savant_url` field).
Format: `**{Away} {away_score}, {Home} {home_score}** — {STL W or L} at {venue}. WP: {name}. LP: {name}. SV: {name if present}. · [Baseball Savant ↗]({savant_url})`

**(b) Line Score table.** Pull values from POSTGAME DATA's `line_score` block — DO NOT invent inning scores. Build a markdown table with one column per inning that was played, plus R / H / E totals. Two rows: away team (top), home team (bottom). Use the actual team names from `away_team` / `home_team`. Right-align numerics. Example shape (replace inning count and values with the real data):

```
### Line Score

| Team | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | R | H | E |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| St. Louis Cardinals | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 2 | 7 | 1 |
| San Diego Padres    | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 1 | 0 | 4 | 5 | 0 |
```

If the game went extras, add columns 10, 11, etc. If `line_score` is null, omit this whole subsection (and note "Line score unavailable").

**(c) Box score tables.** Render Savant-style — the standard slash line PLUS Statcast columns on the batter table. Pull values from POSTGAME DATA `boxscore`. Use the player's full name (linker requires it). For batters use the order shown (lineup order). For pitchers preserve the order they appeared.

The batter rows include `max_ev_mph`, `max_hit_distance_ft`, `best_xba`, `best_outcome`, and `batted_balls` when the player put a ball in play. If a column is null for a player (e.g., they walked twice and never made contact), leave that cell as `—`. xBA values render with three decimals (e.g., `.412`).

```
### Cardinals Batters

| Player | Pos | AB | R | H | RBI | BB | K | HR | Max EV | Hit Dist | xBA on Contact |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Player Name | 2B | 4 | 1 | 1 | 0 | 0 | 1 | 0 | 85.1 mph | 212 ft | .930 (1B) |
| ... |
```

The "xBA on Contact" cell shows the best xBA across the player's batted balls, with the outcome of THAT batted ball in parens (e.g., `.930 (1B)` for a single that had .930 xBA). Use `.000 (Out)` when applicable.

```
### Cardinals Pitchers

| Player | IP | H | R | ER | BB | K | HR | Pitches | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Player Name | 6.0 | 3 | 2 | 2 | 2 | 7 | 1 | 97 | L, 3-4 |
| ... |
```

**(d) Statcast highlights.** Two clearly-labeled groups (Hitters and Pitchers). Pull from `statcast_highlights`. Skip any bucket that is empty or missing. Each bullet must include the specific numeric values from the data — do NOT round or paraphrase. The expected-value metric is xBA (expected batting average) when present; some legacy data may still use xwOBA — render whichever field actually appears in the data block.

```
### Statcast Highlights

**Hitters**
- **Hardest hit:** Player Name — {ev} mph EV, {xba} xBA, {outcome}
- **Best xBA on contact:** Player Name — {xba} ({ev} mph, {outcome})
- **Barrels:** Player Name — {ev} mph, {la}° LA ({outcome})

**Pitchers**
- **Top velocity:** Pitcher Name — {velo} mph {pitch_type} ({outcome})
- **Top whiffs (swinging strikes):** Pitcher Name — {velo} mph {pitch_type} (spin {spin_rpm} rpm)
- **Best putaway pitches (K-ending):** Pitcher Name — {velo} mph {pitch_type} ({result})
- **Lowest xBA allowed (best contact suppression):** Pitcher Name — {pitch_type} {velo} mph, {xba} xBA ({outcome})
```

If a sub-bucket has multiple entries (top 3), list each on its own line.

**(d.5) Win Probability Swings.** Header it `### Win Probability Swings`. Render the top 4-5 plays from POSTGAME DATA's `wpa.key_swings` as a markdown table, in WPA-impact order (largest |Δ| first, which is how the data already arrives). These are the at-bats that *actually moved the game*, with per-pitch context. Skip this whole subsection if `wpa.key_swings` is absent or empty.

```
### Win Probability Swings

| Moment | Δ WP | Batter (Team) vs Pitcher | Result |
|---|---:|---|---|
| B9 | +48.5% | Nick Castellanos (SD) vs Riley O'Brien | HR on 98.5 mph Sinker, 105.2 mph EV |
| T4 | −21.7% | Jordan Walker (STL) vs Walker Buehler | HR on 76.3 mph Knuckle Curve, 108.3 mph EV |
| T10 | +12.0% | José Fermín (STL) vs Adrian Morejon | Pop Out on 98.8 mph Sinker (rally ends) |
| ... |
```

Δ WP is the **home-team** win-probability change for that at-bat (positive = home gained, negative = home lost). Format the Result cell as a one-clause description that names the pitch type, pitch velocity, and either EV/outcome or context — pull from `description`, `pitch_type`, `pitch_velo_mph`, and `ev_mph`. Use the original Unicode minus sign `−` for negative deltas (not a hyphen).

**(e) Scout Notes.** Header it `### Scout Notes` and write 3-5 bullets of scout-flavored color commentary. Each bullet:
- Short (one sentence, scout-flavored, declarative)
- Reference at least ONE specific value from the postgame data (a velocity, an exit velocity, an xwOBA, a count situation, etc.) — do NOT generalize without a number
- Situation-aware: tie pitch metrics to result (e.g., "Dustin May's third 99 mph sinker of the night caught Tatis Jr. looking on the inner half")
- Beat-writer voice (third person, no "I" / "we")
- Vary across the game — don't pile all 5 bullets on one pitcher or one at-bat

NEVER invent a number for these bullets. If the data block doesn't contain it, do not write the bullet.

**(f) Game analysis.** Three paragraphs of beat-writer prose, **driven entirely by the POSTGAME DATA block** — no citations to blogs, podcasts, or other expert content in this subsection. The blog/podcast material is for Cardinals Notebook, not the game story.

Use the gamefeed data sources in this priority order. Every claim must tie to a specific datum:

- **`wpa.key_swings`** — THE narrative spine. These are the top 6 individual at-bats by |WPA Δ|, each with the batter, pitcher, pitch type, pitch velocity, EV, event, and the full play description. Build the game arc around these — the +48.5% swing was the *moment* the game pivoted, not just one of many homers. Reference at least 3-4 of these by name and metric in the narrative.
- **`scoring_plays`** — chronological scoring sequence with the batter/pitcher/EV/xBA/pitch-velo that produced each. Use these to fill in the connective tissue between key swings.
- **`game_context.final_play`** — if the game ended on a scoring play (walk-off), open or close with it explicitly.
- **`game_context.linescore_note`** — phrases like "One out when winning run scored" are pure beat-writer color; work them in naturally.
- **`wpa.top_wpa_players`** — cumulative game WPA leaders (any team). The leader is often the right protagonist for the lede or kicker even if their box-score line isn't loudest. Combine with `key_swings` to triangulate the actual hero/goat.
- **`wpa.last_plays`** — the last 3 plays of the game in chronological order; useful for kicker-paragraph color.
- **`top_performers`** — MLB's own curated standouts. Use the `pitching_line` / `batting_line` strings verbatim when possible (e.g., "5.0 IP, 0 ER, 5 K, 4 BB"). Distinguish Cardinals (`is_stl: true`) from opponents.
- **`game_context.weather` / `wind` / `attendance` / `game_time`** — sprinkle for scene-setting (one mention max — don't make this a weather report).
- **`game_context.abs_challenges`** — note when ABS challenges flipped a call in a leverage spot; reference the player.
- **`statcast_highlights`** — pull specific EV/xBA/velo numbers to back up claims already established by scoring_plays (e.g., "Walker's 11th of the year, hit at {ev} mph with a {xba} xBA").
- **`boxscore.batters` / `boxscore.pitchers`** — for context lines (who else was in the lineup, bullpen usage).

End with one line on what's at stake going forward — but only mention the series score, standings, or upcoming opponent if that information is in POSTGAME DATA. Do not invent it.

If POSTGAME DATA is null (off day), say so directly and pivot to the most recent game discussed in the expert content with whatever detail is available — no fabricated boxscores or line scores.

## Cardinals Notebook

The state of the Cardinals between and around the lines — roster, performance, narratives, off-field. This is the report's analytical core. 700-1100 words. Use ### subheaders for individual players or distinct sub-beats; flowing prose otherwise.

Cover, organized into a coherent narrative (NOT a bullet dump):

**Standings & shape.** Where the team sits in the division and league. Underlying signals (run differential, record vs .500-plus opponents, one-run / extra-inning record, high-leverage wRC+, etc.) — every figure cited from the provided content with source + date.

**On-field performance.**
- Rotation: who's pitching well, mechanics changes, velocity, command, recent starts.
- Bullpen: closer situation, high-leverage usage, role shifts, anyone losing trust.
- Lineup hot/cold: regulars trending up or down with specific stats (BA, OPS, K%, wRC+, HR pace).
- Notable individual storylines worth a ### subheader (e.g., an MVP candidate, a breakout rookie, a struggling veteran).

**Roster & transactions.** Moves in the last 5 days (call-ups, IL placements, DFAs, waiver claims), and any names being floated in trade chatter. Manager (Oli Marmol) decisions worth flagging — lineup construction, platoon usage, bullpen leverage.

**Around the conversation.** What recurring narratives are surfacing across blogs, podcasts, and beat writers? Where do sources disagree on the same player or storyline (cite who is bullish vs bearish)? What off-field items are surfacing — Chaim Bloom posture, ownership notes, coaching, broadcast / media notes, market comps?

**No internal repetition.** Discuss each player or storyline ONCE in this section. If Walker's MVP buzz is the right hook for the standings paragraph, it lives there; do not also create a separate "Around the conversation" paragraph re-citing the same sources for the same point. The section is one continuous synthesis, not a stack of overlapping sub-essays.

## Beat Writer's Verdict

Two to three paragraphs closing the report from a third-person beat-writer POV. Cover:

- What Cardinals fans should feel encouraged about today (specific reason backed by data or quote)
- What's quietly worrying (with the underlying number)
- The next series and what to watch for, IF the source content or postgame data names the next opponent — otherwise skip
- One concrete thing that would shift the picture meaningfully in 7 days

End with a single sharp line. Beat-writer voice — declarative, sourced, not "I think".

## Around the League

A closing 5-7 bullet roundup of league-wide MLB headlines from the last 24 hours, drawn from the MLB NEWS HEADLINES block at the bottom of this prompt.

**STRICT FILTER — only include items in these categories:**
- Game results, milestones, individual performance (e.g., "Player X struck out 12", "Team Y swept opponent Z")
- Transactions: trades, signings, extensions, DFAs, waiver claims
- Injuries / IL / rehab / activations
- Suspensions, fines, disciplinary
- Roster moves, call-ups, demotions
- Standings shifts, playoff/wild-card position notes
- Front office moves, manager hires/fires, coaching changes

**EXCLUDE — do NOT include items like:**
- Human-interest stories ("Player honors late mother", "Family in the stands on Mother's Day")
- Tributes, anniversaries, charity events, Make-A-Wish, memorial pieces
- Off-field non-baseball news, broadcasting/media-business stories not tied to a player
- Clickbait headlines ("Why is this manager wearing catcher's gear?")
- Items that are clearly about another sport or non-MLB content

Format each bullet — the headline MUST be a markdown link to the source URL provided in the MLB NEWS HEADLINES block:

`- **[{succinct headline}]({url})** — one sentence of context tying it to the on-field outcome or fantasy/standings implication. *({Source})*`

The `{url}` is the URL line that appears directly under each candidate item in the MLB NEWS HEADLINES block. Always use it; never write the headline as plain text. If a candidate item has no URL line, skip that item entirely rather than writing an unlinked bullet.

If fewer than 5 qualifying items exist in the input, list however many qualify. If none qualify (rare), write a single line: "Quiet news day across MLB."

Do NOT fabricate headlines or URLs. Every bullet's link must trace back to a URL in the MLB NEWS HEADLINES block.

## Interesting Analysis

The closing section: 4-6 deep-dive items from the BASEBALL ANALYSIS HEADLINES block (general baseball writing + analytical podcast episodes). This is NOT a news roundup — these are pieces a thoughtful baseball fan would want to read or listen to on the bus.

**STRICT FILTER — only include items that are:**
- General baseball analysis: scouting, mechanics, pitch design, hitter approach, defensive metrics, advanced stats explainers
- Historical pieces, oral histories, longreads
- League-wide trends: rule changes (ABS challenge etc.), strategy shifts, financial / labor stories that matter
- Analytical podcast episodes (Effectively Wild, FanGraphs Audio, segments of fantasy podcasts that are actually about baseball)

**EXCLUDE — do NOT include:**
- Fantasy-focused items: rankings, draft prep, projections, ADP, waiver wire, start/sit, lineup optimizer, DFS, dynasty
- Cardinals-specific items (they have their own section above; no duplication)
- Wire-service headlines (those went in Around the League)
- Pure highlight clips or "watch this catch" pieces

Format each bullet — the headline MUST be a clickable markdown link to the article/episode URL from the BASEBALL ANALYSIS HEADLINES block:

`- **[{succinct headline}]({url})** — one or two sentences on why this piece is interesting / what it actually argues. *({Source})*`

The `{url}` is the URL line under each candidate item. Always use it. If a candidate has no URL line, skip it.

Order the bullets by how interesting they are (most compelling first), not by recency.

If fewer than 4 qualifying items exist after the filter, list however many qualify. If none qualify, write a single line: "Quiet day for baseball longform."

Do NOT fabricate. Every link traces back to a URL in the BASEBALL ANALYSIS HEADLINES block."""
)


def build_prompt(
    today: date,
    content_block: str,
    postgame: dict | None,
    mlb_headlines: list[dict] | None = None,
    analysis_headlines: list[dict] | None = None,
) -> str:
    parts: list[str] = []

    parts.append(
        f"Write the daily St. Louis Cardinals intelligence report for {today.strftime('%B %d, %Y')}.\n\n"
        "Sections (in this exact order, ## level): "
        "Score and Data for {Month D, YYYY} (where the date is the actual game date from POSTGAME DATA), "
        "Cardinals Notebook, Beat Writer's Verdict, Around the League, Interesting Analysis.\n\n"
        "Do NOT add any other sections. No 'Previous Game', no 'MLB Cardinals', no 'MLB News Brief', "
        "no 'Around the Internet', no 'Minor League Cardinals', no 'Sibling Rivalry', no 'Cardinals Corner'. "
        "Five sections only.\n\n"
    )
    parts.append(SECTION_INSTRUCTIONS)

    parts.append("\n\n---\n\n# POSTGAME DATA (yesterday's MLB Cardinals game)\n\n")
    if postgame:
        parts.append("```json\n")
        parts.append(json.dumps(postgame, indent=2, default=str))
        parts.append("\n```\n")
    else:
        parts.append("`null` — no Cardinals game on the target date (off day or postponed).\n")

    parts.append("\n---\n\n# EXPERT CONTENT (Cardinals-specific blogs and podcasts)\n\n")
    parts.append(content_block)

    parts.append("\n\n---\n\n# MLB NEWS HEADLINES (last 24 hours, league-wide)\n\n")
    if mlb_headlines:
        parts.append(
            f"_{len(mlb_headlines)} candidate items below. Apply the strict filter in the "
            "'Around the League' section instructions — exclude human-interest, tributes, "
            "anniversaries, clickbait, and non-baseball-action items._\n\n"
        )
        for h in mlb_headlines:
            line = f"- **{h['title']}**"
            if h.get("source"):
                line += f"  _({h['source']})_"
            if h.get("summary"):
                line += f"\n  {h['summary']}"
            if h.get("url"):
                line += f"\n  {h['url']}"
            parts.append(line + "\n")
    else:
        parts.append("_(No headlines available — write 'Quiet news day across MLB.')_\n")

    parts.append(
        "\n\n---\n\n# BASEBALL ANALYSIS HEADLINES (last 72 hours, mixed analysis + fantasy feeds)\n\n"
    )
    if analysis_headlines:
        parts.append(
            f"_{len(analysis_headlines)} candidate items below from FanGraphs, Pitcher List, "
            "RotoWire, Effectively Wild, FanGraphs Audio, and fantasy podcasts. Apply the "
            "strict filter in the 'Interesting Analysis' section instructions — "
            "EXCLUDE fantasy-focused items (rankings, draft, projections, waiver, start/sit, DFS, dynasty) "
            "and EXCLUDE Cardinals-specific items (they already have their own section). "
            "Pick 4-6 GENERAL baseball analysis deep dives._\n\n"
        )
        for h in analysis_headlines:
            line = f"- **{h['title']}**"
            if h.get("source"):
                line += f"  _({h['source']})_"
            if h.get("summary"):
                line += f"\n  {h['summary']}"
            if h.get("url"):
                line += f"\n  {h['url']}"
            parts.append(line + "\n")
    else:
        parts.append("_(No analysis headlines available — write 'Quiet day for baseball longform.')_\n")

    return "".join(parts)


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------


def _defeat_blot_heading_titlecase(markdown: str) -> str:
    """Insert zero-width spaces between adjacent uppercase letters in heading lines.

    Blot title-cases all-caps words inside <h*> tags at the source level
    (`JJ` → `Jj`, `MLB` → `Mlb`). Inserting U+200B between letters makes
    Blot see them as separate single-letter "words" so it skips the
    transformation. The character is invisible in rendered HTML.

    Only operates on lines that start with `#` (heading markdown). Preserves
    URL contents inside `(...)` so we don't corrupt markdown links.
    """
    zwsp = "​"

    def split_caps(m: re.Match) -> str:
        return zwsp.join(m.group(0))

    out_lines: list[str] = []
    for line in markdown.split("\n"):
        if not line.lstrip().startswith("#"):
            out_lines.append(line)
            continue
        # Split on parenthesized URLs to avoid mangling links.
        # Even-index parts = text (transform), odd-index = `(url)` (leave alone).
        parts = re.split(r"(\([^)]*\))", line)
        for i in range(0, len(parts), 2):
            parts[i] = re.sub(r"[A-Z]{2,}", split_caps, parts[i])
        out_lines.append("".join(parts))
    return "\n".join(out_lines)


def _format_blot_title(today: date, postgame: dict | None) -> str:
    """Build the Blot post Title from postgame data.

    Uses the GAME date (yesterday) for the date stamp — not today's report date.

    Examples:
      "@ Padres 2-4 (L) — May 9"
      "vs. Reds 7-3 (W) — May 11"
      "Cardinals — May 10 (off day)"   ← falls back to today when no game
    """
    if not postgame:
        return f"Cardinals — {today.strftime('%B %-d')} (off day)"

    # Pull the actual game date from postgame.date (ISO YYYY-MM-DD); fall back to today.
    try:
        game_date = date.fromisoformat(postgame.get("date") or "")
        date_short = game_date.strftime("%B %-d")
    except (TypeError, ValueError):
        date_short = today.strftime("%B %-d")

    ls = postgame.get("line_score") or {}
    totals = ls.get("totals") or {}
    stl_is_home = bool(postgame.get("stl_is_home"))

    if stl_is_home:
        stl_r = ((totals.get("home") or {}).get("R")) or 0
        opp_r = ((totals.get("away") or {}).get("R")) or 0
        opp_full = postgame.get("away_team") or "Opponent"
        connector = "vs."
    else:
        stl_r = ((totals.get("away") or {}).get("R")) or 0
        opp_r = ((totals.get("home") or {}).get("R")) or 0
        opp_full = postgame.get("home_team") or "Opponent"
        connector = "@"

    opp_short = opp_full.split()[-1] if opp_full else "Opponent"
    if stl_r > opp_r:
        wl = "W"
    elif stl_r < opp_r:
        wl = "L"
    else:
        wl = "T"
    return f"{connector} {opp_short} {stl_r}-{opp_r} ({wl}) — {date_short}"


def _extract_summary(postgame: dict | None) -> str:
    """One-line summary for Blot's Summary: metadata + homepage preview."""
    if not postgame:
        return "Cardinals off day."
    matchup = postgame.get("matchup") or ""
    result = postgame.get("result") or ""
    # Result is like "St. Louis Cardinals 2, San Diego Padres 4 (STL L)"
    # Strip the (STL X) suffix and shorten "St. Louis Cardinals" → "Cardinals"
    cleaned = re.sub(r"\s*\(STL [WLT]\)\s*$", "", result).replace("St. Louis Cardinals", "Cardinals")
    venue = postgame.get("venue") or ""
    if cleaned and venue:
        return f"{cleaned} at {venue}."
    return cleaned or matchup or "Cardinals daily intel report."


def _publish_to_blot(
    today: date,
    body_text: str,
    player_links: dict[str, str],
    postgame: dict | None = None,
) -> Path | None:
    """Drop a Blot-formatted markdown post into the Dropbox/Blot/Posts folder.

    Blot uses its own metadata format (key: value at top, blank line, body) — not
    YAML. The body markdown is the linkified report content, minus the YAML
    frontmatter we use locally.

    Tags are deliberately omitted because Blot's tag rendering on this template
    fell through the parent context (chips appeared empty or showed the filename).

    Returns the written path, or None if the folder is unavailable.
    """
    if not BLOT_POSTS_DIR.exists():
        log.warning("Blot Posts folder not found at %s — skipping publish", BLOT_POSTS_DIR)
        return None

    linked = linkify_players(body_text, player_links) if player_links else body_text
    title = _format_blot_title(today, postgame)
    summary = _extract_summary(postgame)

    # Blot metadata header. Blank line separates metadata from post body.
    blot_header = (
        f"Title: {title}\n"
        f"Date: {today.isoformat()}\n"
        f"Summary: {summary}\n"
        f"Link: cardinals-daily-{today.isoformat()}\n"
        "\n"
    )

    # Strip the leading H1 (whatever it says) — Blot derives the title from
    # the metadata above. Old regex was too narrow; this matches any first H1.
    body = re.sub(r"^\s*#\s+.+?\n+", "", linked.lstrip(), count=1)

    # Defeat Blot's source-level title-casing of all-caps words inside headings
    # (`### JJ Wetherholt` → `<span class="small-caps">Jj</span> Wetherholt`).
    # ZWSP between adjacent capitals breaks the detection but is invisible.
    body = _defeat_blot_heading_titlecase(body)

    post_path = BLOT_POSTS_DIR / f"{today.isoformat()}-cardinals-daily.md"
    post_path.write_text(blot_header + body, encoding="utf-8")
    log.info("Published to Blot: %s (title: %s)", post_path.name, title)
    return post_path


def write_report(
    today: date,
    body_text: str,
    items: list[dict],
    input_tokens: int,
    output_tokens: int,
    player_links: dict[str, str],
) -> Path:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ANALYSIS_DIR / f"{today.isoformat()}_{REPORT_SLUG}.md"

    linked = linkify_players(body_text, player_links) if player_links else body_text
    sources = build_sources_section(items)

    frontmatter = (
        "---\n"
        f"title: \"Cardinals Daily — {today.strftime('%B %d, %Y')}\"\n"
        f"type: {REPORT_SLUG}\n"
        f"date: {today.isoformat()}\n"
        f"generated_at: {datetime.now(timezone.utc).isoformat()}\n"
        f"input_tokens: {input_tokens}\n"
        f"output_tokens: {output_tokens}\n"
        "---\n\n"
        f"# Cardinals Daily — {today.strftime('%B %d, %Y')}\n\n"
    )

    body = linked.strip() + "\n\n" + sources + "\n" if sources else linked.strip() + "\n"
    out_path.write_text(frontmatter + body, encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(force: bool = False, days: int = CONTENT_WINDOW_DAYS, dry_run: bool = False) -> None:
    today = date.today()
    out_path = ANALYSIS_DIR / f"{today.isoformat()}_{REPORT_SLUG}.md"

    if out_path.exists() and not force and not dry_run:
        log.info("Today's Cardinals report already exists at %s (use --force to regenerate)", out_path)
        return

    target_postgame_date = today - timedelta(days=1)
    log.info("Fetching postgame data for %s", target_postgame_date.isoformat())
    postgame = None
    try:
        postgame = get_cardinals_postgame(target_postgame_date)
    except Exception as e:
        log.warning("Postgame fetch failed: %s — proceeding without postgame data", e)

    items = load_cardinals_content(days=days)
    if not items and postgame is None:
        log.warning(
            "No Cardinals content AND no postgame data — generating may produce thin report"
        )

    content_block = build_content_block(items)

    log.info("Fetching MLB-wide news headlines (last 24h)...")
    try:
        mlb_headlines = fetch_mlb_news_headlines(hours=24, max_items=25)
        log.info("Fetched %d MLB headlines", len(mlb_headlines))
    except Exception as e:
        log.warning("MLB news fetch failed entirely: %s", e)
        mlb_headlines = []

    log.info("Fetching baseball analysis headlines (last 72h)...")
    try:
        analysis_headlines = fetch_analysis_headlines(hours=72, max_items=40)
        log.info("Fetched %d analysis headlines", len(analysis_headlines))
    except Exception as e:
        log.warning("Analysis headlines fetch failed entirely: %s", e)
        analysis_headlines = []

    user_message = build_prompt(today, content_block, postgame, mlb_headlines, analysis_headlines)

    if dry_run:
        log.info("=== DRY RUN ===")
        log.info("System prompt: %d chars", len(SYSTEM_PROMPT))
        log.info("User message: %d chars (~%d tokens)", len(user_message), len(user_message) // 4)
        log.info("Postgame data present: %s", postgame is not None)
        log.info("Cardinals content items: %d", len(items))
        log.info("MLB headlines: %d", len(mlb_headlines))
        log.info("Analysis headlines: %d", len(analysis_headlines))
        return

    if not USE_CLAUDE_CLI:
        log.error("Cardinals report only supports CLI (subscription) mode currently. Aborting.")
        return

    log.info("Generating Cardinals report via Claude Code subscription (claude -p)...")
    try:
        text, in_toks, out_toks, stop = _invoke_claude_cli(MODEL, SYSTEM_PROMPT, user_message)
    except Exception as e:
        log.error("Cardinals report generation failed: %s", e)
        return

    if not text:
        log.error("Empty response from Claude. Aborting Cardinals report.")
        return

    log.info(
        "Generated: %d words, %d input tokens, %d output tokens (stop: %s)",
        len(text.split()), in_toks, out_toks, stop,
    )

    player_links = load_player_links()
    out = write_report(today, text, items, in_toks, out_toks, player_links)
    cost = (in_toks * 5 + out_toks * 25) / 1_000_000
    log.info("Done. Wrote %s (~$%.2f subscription quota, not billed)", out, cost)

    # Publish to Blot. Non-fatal — if Dropbox is unmounted or path missing, we log and move on.
    try:
        _publish_to_blot(today, text, player_links, postgame=postgame)
    except Exception as e:
        log.warning("Blot publish failed (non-fatal): %s", e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Cardinals intelligence report")
    parser.add_argument("--force", action="store_true", help="Regenerate even if today's exists")
    parser.add_argument("--dry-run", action="store_true", help="Preview prompt without API call")
    parser.add_argument(
        "--days", type=int, default=CONTENT_WINDOW_DAYS,
        help=f"Content lookback window in days (default: {CONTENT_WINDOW_DAYS})",
    )
    args = parser.parse_args()
    run(force=args.force, days=args.days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
