#!/usr/bin/env python3
"""Daily St. Louis Cardinals intelligence report.

Sibling to scripts.daily_analysis but scoped to Cardinals-only content
(Locked On Cardinals podcast, Viva El Birdos, Redbird Rants, The Cardinal
Nation) plus postgame Statcast data via app.services.cardinals_postgame.

Generates a single markdown at data/content/analysis/{today}_cardinals-daily.md
with four sections: Previous Game, MLB Cardinals, Minor League Cardinals,
Fan Takeaway. Uses Opus 4.8 via the Max-subscription claude -p path.

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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import feedparser
import httpx
from dotenv import load_dotenv

from app.services.cardinals_postgame import (
    get_cardinals_next_game,
    get_cardinals_postgame,
)
from app.services.og_banner import generate_og_banner
from app.services.player_linking import linkify_players, load_player_links

# Reuse battle-tested helpers from the fantasy report
from scripts.daily_analysis import (
    MAX_CONTENT_CHARS,
    _invoke_claude_cli,
    parse_frontmatter,
)
from scripts.factcheck_cardinals import (
    extract_score_and_data,
    factcheck_score_and_data,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = PROJECT_ROOT / "data" / "content"
BLOGS_DIR = CONTENT_DIR / "blogs"
TRANSCRIPTS_DIR = CONTENT_DIR / "transcripts"
ANALYSIS_DIR = CONTENT_DIR / "analysis"
# Reports that fail fact-check twice land here instead of ANALYSIS_DIR so the
# downstream pipeline (PDF render, Readdle sync, Fly upload) glob does not pick
# them up. The 4 AM verifier reads this dir to escalate.
FACTCHECK_FAILED_DIR = ANALYSIS_DIR / "factcheck_failed"
DB_PATH = PROJECT_ROOT / "fantasy_baseball.db"

load_dotenv(PROJECT_ROOT / ".env")

MODEL = "claude-opus-4-8"
USE_CLAUDE_CLI = os.getenv("DAILY_ANALYSIS_USE_CLI", "1") == "1"
CONTENT_WINDOW_DAYS = 5
REPORT_SLUG = "cardinals-daily"
# Cap on fact-check + surgical-edit iterations before quarantine. Each pass is
# one Opus call (~2 min). The 3 AM cron tolerates the runtime in exchange for
# converging on a publishable post automatically rather than landing in
# factcheck_failed/ for manual intervention.
MAX_FACTCHECK_ATTEMPTS = 6

# Feed keys (matched against the {date}_{key}_*.md filename prefix)
CARDINALS_SOURCES: set[str] = {
    "viva_el_birdos",
    "redbird_rants",
    "cardinal_nation",
    "locked_on_cardinals",
    "walton_and_reis",
    "bschaeff_daily",
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
    (
        "FantasyPros Baseball",
        "https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/"
        "03db435f-86aa-4395-95a3-b2d70144b868/a32aaa57-276f-4ebd-af98-b2d70144b87c/podcast.rss",
    ),
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
                items.append(
                    {
                        "title": meta.get("title", fp.stem),
                        "source_name": meta.get("source_name", meta.get("source", "Unknown")),
                        "url": meta.get("url", ""),
                        "date": date_str,
                        "date_parsed": pub,
                        "content": body,
                        "type": content_type,
                        "filename": fp.name,
                        "word_count": len(body.split()),
                    }
                )
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


def _fetch_rss_headlines(feeds: list[tuple[str, str]], hours: int, max_items: int) -> list[dict]:
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
            items.append(
                {
                    "title": title,
                    "summary": summary[:400],
                    "source": source_name,
                    "url": entry.get("link", ""),
                    "published": pub_dt.isoformat() if pub_dt else None,
                }
            )
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
            f'### [{item["type"].title()}] "{item["title"]}" — {item["source_name"]}'
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
# Source linking (blog/podcast homepage + per-article URL lookup)
# ---------------------------------------------------------------------------


# Homepage URLs for Cardinals media outlets. Used for inline mentions
# ("Locked On Cardinals relayed..." → linked) and as a fallback when a
# citation's date doesn't resolve to a unique ingested article.
#
# Includes outlets we DON'T ingest (Cardinal Territory) but that get
# mentioned in prose. Order matters for substring matching: longer
# canonical names must appear before shorter prefixes that overlap.
SOURCE_HOMEPAGES: dict[str, str] = {
    "Wednesday With Walton and Reis": "https://podcasters.spotify.com/pod/show/brian54",
    "Locked On Cardinals": "https://lockedonpodcasts.com/podcasts/locked-on-st-louis-cardinals/",
    "Viva El Birdos": "https://www.vivaelbirdos.com/",
    "Redbird Rants": "https://redbirdrants.com/",
    "The Cardinal Nation": "https://www.thecardinalnation.com/",
    "Cardinal Territory": "https://twitter.com/CardTerritory",
    "Walton and Reis": "https://podcasters.spotify.com/pod/show/brian54",
    "B-Schaeff Daily": "https://anchor.fm/bschaeffer12",
}

# Maps the display name used in prose to the manifest `source` key used for
# per-article URL lookup. Outlets not in this map (Cardinal Territory) fall
# through to homepage-only.
SOURCE_NAME_TO_KEY: dict[str, str] = {
    "Viva El Birdos": "viva_el_birdos",
    "Redbird Rants": "redbird_rants",
    "Locked On Cardinals": "locked_on_cardinals",
    "The Cardinal Nation": "cardinal_nation",
    "Wednesday With Walton and Reis": "walton_and_reis",
    "Walton and Reis": "walton_and_reis",
    "B-Schaeff Daily": "bschaeff_daily",
}

MANIFEST_PATH = CONTENT_DIR / "manifest.json"

_MONTH_NUMS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def load_source_articles(report_date: date) -> dict[tuple[str, str], str]:
    """Build a (source_key, ISO_date) → article URL map from manifest.json.

    Loads all ingested Cardinals-source articles. When the report cites
    *(Redbird Rants, May 9)*, the citation matcher looks up
    ("redbird_rants", "2026-05-09") in this map. If exactly one article
    matches, the citation is linked to that article; if multiple or none
    match, the citation falls back to the source homepage.
    """
    articles: dict[tuple[str, str], list[str]] = {}
    if not MANIFEST_PATH.exists():
        return {}
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Could not load manifest.json: %s", e)
        return {}
    for section in ("blogs", "transcripts"):
        for _fn, item in (manifest.get(section) or {}).items():
            src_key = item.get("source")
            if src_key not in CARDINALS_SOURCES:
                continue
            url = item.get("url") or ""
            date_str = (item.get("date") or "")[:10]
            if not url or not date_str:
                continue
            articles.setdefault((src_key, date_str), []).append(url)
    # Keep only single-article keys so citations resolve unambiguously.
    return {k: v[0] for k, v in articles.items() if len(v) == 1}


def _parse_citation_date(date_str: str, report_date: date) -> str | None:
    """Parse a citation date like 'May 9' or 'May 9, 2026' into ISO YYYY-MM-DD.

    Uses the report year if no year is supplied. Returns None on parse failure.
    """
    s = date_str.strip().rstrip(".").rstrip(",")
    # Try 'Month D, YYYY' first
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2})(?:,\s*(\d{4}))?$", s)
    if not m:
        return None
    month_word, day, year = m.group(1).lower(), int(m.group(2)), m.group(3)
    month = _MONTH_NUMS.get(month_word)
    if not month:
        return None
    y = int(year) if year else report_date.year
    try:
        return date(y, month, day).isoformat()
    except ValueError:
        return None


def linkify_sources(
    text: str,
    homepages: dict[str, str],
    articles: dict[tuple[str, str], str],
    report_date: date,
) -> str:
    """Convert source-name mentions and italic citations into markdown links.

    Two passes:
      1. Citations matching ``*(Source Name, Date)*`` → ``*([Source Name](url), Date)*``.
         If the (source_key, ISO date) is in the manifest article map with exactly
         one article, that article URL is used. Otherwise the source homepage URL
         is used.
      2. Inline source name mentions (e.g. "Viva El Birdos noted...") get linked
         to the source's homepage URL. Existing markdown links are preserved by
         splitting on link spans and only operating on the non-link chunks.

    The post-processor is intentionally conservative: a source name already
    surrounded by ``[...](...)`` is never re-linked, and citations whose source
    name doesn't appear in either map are left as plain italics.
    """
    if not text:
        return text

    # Pass 1: italic citations
    def cite_repl(m: re.Match) -> str:
        src_name = m.group(1).strip()
        date_str = m.group(2).strip()
        # If the citation already contains a markdown link, skip
        if "[" in src_name or "]" in src_name:
            return m.group(0)
        homepage = homepages.get(src_name)
        url = None
        src_key = SOURCE_NAME_TO_KEY.get(src_name)
        iso = _parse_citation_date(date_str, report_date)
        if src_key and iso:
            url = articles.get((src_key, iso))
        if not url:
            url = homepage
        if not url:
            return m.group(0)
        return f"*([{src_name}]({url}), {date_str})*"

    text = re.sub(
        r"\*\(([^,\(\)\[\]]+?),\s*([^\(\)\[\]]+?)\)\*",
        cite_repl,
        text,
    )

    # Pass 2: inline mentions. Split on existing markdown links so we don't
    # double-link source names that already appear inside a [..](..) span.
    parts = re.split(r"(\[[^\]]+\]\([^)]+\))", text)
    # Match longest source names first so "Wednesday With Walton and Reis"
    # is tried before "Walton and Reis".
    ordered = sorted(homepages.items(), key=lambda kv: len(kv[0]), reverse=True)
    for i in range(0, len(parts), 2):  # even indices = non-link text
        chunk = parts[i]
        for src_name, url in ordered:
            pattern = r"\b" + re.escape(src_name) + r"\b"
            chunk = re.sub(
                pattern,
                lambda m, n=src_name, u=url: f"[{n}]({u})",
                chunk,
            )
        parts[i] = chunk

    return "".join(parts)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = (
    "You are a St. Louis Cardinals beat writer in the Bernie Miklasz / Derrick Goold tradition. "
    "Stat-driven, knowledgeable about the 26-man roster, the bullpen, the rotation, and the farm system. "
    "Write in **THIRD PERSON** about the Cardinals: 'the Cardinals', 'St. Louis', 'their rotation', "
    "'the Cardinals' prospect pipeline'. NEVER use 'I', 'me', 'we', 'us', 'our'. The reader is a fan. "
    "The writer is a reporter. Stat-driven authority, but the prose breathes. Numbers serve the "
    "story; the story is not a list of numbers. Pick the moments where a metric earns its mention "
    "and let the rest read as English. No glib hot takes. No fan-rant first person.\n\n"
    "PROSE RULES (apply to all prose in Game Analysis, Cardinals Notebook, Beat Writer's Verdict, "
    "and the trailing description sentence of every Around the League / Interesting Analysis bullet):\n"
    "- NEVER use em dashes (—). Replace with periods, commas, colons, or restructure the sentence.\n"
    "- Do NOT add a comma before 'and' or 'but' in a compound sentence. Oxford commas in lists of three\n"
    "  or more are fine.\n"
    "- Do NOT use corrective contrast ('not X but Y' / 'wasn't X, it was Y' / 'isn't X, it's Y'). State Y\n"
    "  directly. Trust the reader to infer what Y excludes. The only exception: if the reader genuinely\n"
    "  holds the wrong belief and you are correcting it.\n"
    "- Do NOT open paragraphs with false-transition phrases: 'Here's the thing', 'What's interesting is',\n"
    "  'It's worth noting that', 'The reality is', 'But here's the catch', 'To be clear', 'At its core',\n"
    "  'This matters because', 'Let's be honest', 'The truth is', 'What people don't realize is'.\n"
    "- Do NOT open a paragraph with a pronoun whose referent is only in the previous paragraph.\n"
    "- Do NOT restate a point you just made in different words. Do not telegraph a conclusion before\n"
    "  delivering it. Do not narrate your own rhetorical moves.\n"
    "- METRIC RESTRAINT (Game Analysis especially). At most one stat (EV, pitch velo, xBA, WPA, spin\n"
    "  rpm) per sentence, and most sentences should carry none. Real beat writers use three or four\n"
    "  numbers in a 500-word game story, not thirty. Specifically:\n"
    "    * Do NOT cite EV on bunts, soft groundouts, or any contact below ~95 mph unless the soft\n"
    "      contact IS the story (a 70 mph squib that scored a run, a popup that fell for a hit).\n"
    "      A 92 mph flyout is a flyout; do not append the EV.\n"
    "    * Do NOT cite xBA on routine outs. xBA earns a mention on barrels that found a glove or on\n"
    "      a putaway pitch that suppressed contact.\n"
    "    * Do NOT cite spin rate unless it is a genuine outlier or the pitch design IS the angle.\n"
    "    * Pick ONE or TWO pivot moments to anchor with WPA; do not narrate the post-play win\n"
    "      probability after every swing. A name + outcome + leverage description is plenty for\n"
    "      the rest.\n"
    "    * Do NOT stack weather, attendance, time of game, AND a stat into a single sentence.\n"
    "      Scene-setting is one detail at a time, and only when it adds something.\n"
    "  The right cadence is: plain English describing what happened, with a number reached for when\n"
    "  the number is genuinely the moment (a barrel, a 99 mph heater that froze a hitter, a swing\n"
    "  that moved win probability by twenty-plus points). Restraint reads as authority. Stat-stuffing\n"
    "  reads as a feed dump.\n"
    "- Tables, the score-header line, Statcast Highlights bullets, and bullet-list separators "
    "  ('Player Name — 99.7 mph Sinker') are exempt from the em-dash rule. The rule applies to genuine\n"
    "  prose sentences.\n\n"
    "FORMATTING:\n"
    "- ## for section headers, ### for player names or sub-beats\n"
    "- Bold sparingly for tags or key facts (**W**, **L**, **HR**, **IL**)\n"
    "- *Italics* for source citations: *(Locked On Cardinals, May 9)*. The source name will be auto-linked\n"
    "  by a post-processor — write the citation as plain italic text, do not insert markdown links\n"
    "  yourself. Inline mentions of source names ('Viva El Birdos noted...', 'per Locked On Cardinals')\n"
    "  are also auto-linked. Use the exact source name as it appears in the EXPERT CONTENT block.\n"
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
    "- Write polished prose. No stream-of-consciousness self-corrections.\n"
    "- DO NOT be lazy or brief. Each section earns its space.\n\n"
    "HARD RULE: DO NOT DERIVE OR INFER NUMBERS IN THE SCORE AND DATA SECTION.\n"
    "Every numeric claim in the Game Analysis prose must come from an explicit numeric field "
    "in POSTGAME DATA. Do not count, sum, or compute values yourself. The fact-checker is "
    "strict and will flag derived numbers even when they happen to be correct.\n"
    "- RUNS PER INNING ('a four-run fifth', 'three-run sixth'): only assertable when "
    "`line_score.innings[i].away.runs` or `.home.runs` for that inning shows that exact "
    "value. If you cannot point to that field, do not characterize the inning by run total. "
    "Describe the scoring plays individually instead.\n"
    "- PER-PLAY RBI ('two-run homer', 'RBI single', 'three-run double'): only assertable "
    "when the play's `rbi` field confirms it, or the description literally names that many "
    "scorers. A homer with no 'X scores' in the description is a solo homer.\n"
    "- TOTAL RBI for a player: only assertable when `top_performers[].batting_line` for that "
    "player contains an explicit 'N RBI' segment (e.g., '3-4 | HR, 2 RBI'). If batting_line "
    "lists hits/walks but no RBI, omit the total RBI count for that player.\n"
    "- PITCHER EXIT / 'CHASED' / 'KNOCKED OUT' / 'PULLED EARLY' claims: only assertable "
    "from the pitcher's `pitching_line` (which shows IP) and the bbref `play_by_play` (which "
    "shows the last inning the pitcher appears). Do not infer an early exit from when a "
    "team scored. If unsure, state IP only.\n"
    "- OUTS CONTEXT for a play ('two-out homer', 'leadoff single', 'with two on and one out'): "
    "only assertable from the bbref `play_by_play` row's `outs` (outs after the play) and "
    "`runners` (base state before). Do not infer outs from where in the inning the play "
    "appeared. If the data is not there, drop the outs detail.\n"
    "- TEAM ATTRIBUTION for stat lines: read `top_performers[].team_id`. The player belongs "
    "to THAT team in the game, not the opposing one. A double off a Padres pitcher came "
    "from a non-Padres batter; do not attribute the batter to San Diego.\n"
    "- SEASON TOTALS ('his 11th HR', 'her 4th SB', 'doubled (7)'): only assertable when the "
    "play's `season_total` field is present, OR when the `description` contains the explicit "
    "parenthetical 'verbs (N)' format from Savant. Do not invent or round season totals.\n"
    "- STRIKEOUT-INNING claims ('struck out the side', 'three-K inning', 'fanned three in "
    "order'): only assertable when (a) the pitcher's `pitching_line` shows K=3 in a one-inning "
    "appearance, AND (b) the bbref `play_by_play` rows for that inning show three Strikeout "
    "entries for that pitcher. Pitch count alone does not imply K count. If you cannot verify "
    "both, describe what actually happened (e.g., 'worked a clean inning on 10 pitches with "
    "two strikeouts').\n"
    "- BASE-RUNNER ADVANCEMENT ('took second on a wild pitch', 'stole third', 'tagged from "
    "first on the single'): each advancement is its own bbref `play_by_play` row. Read the "
    "`play_desc` text literally. Do NOT conflate consecutive advancements (e.g., Defensive "
    "Indifference followed by Wild Pitch are two separate bases; do not credit the wild pitch "
    "with both). When in doubt, describe the runner's final base and skip the mechanism.\n"
    "- PITCH COUNT for a specific plate appearance ('walked on five pitches', 'struck out on "
    "a 1-2 curveball', 'fouled off three before...'): only assertable from the bbref `pitches` "
    "field on that PA's row, which is formatted 'N,(final-count) sequence' (e.g., '6,(3-2) "
    ".BLC*BBB' = 6 pitches, finished at 3-2). The first integer before the comma is the pitch "
    "count; the parenthetical pair is the final count when the PA ended. Do NOT guess pitch "
    "counts from prose context.\n"
    "- BARREL CLASSIFICATION ('a barreled lineout', 'his barrels included', 'two barrels for "
    "the day'): only assertable when the play appears in `statcast_highlights.barrels`. A "
    "ball appearing in `hardest_hit` is NOT necessarily a barrel; barrels require both high "
    "EV (98+ mph) AND a specific launch-angle window. Check the `barrels` list explicitly.\n"
    "- PITCH-TO-BATTER attribution in statcast_highlights ('a 99.4 mph sinker that froze "
    "Ty France', 'O'Brien's 98.5 punchout of Machado'): every entry in `top_pitches`, "
    "`top_whiffs`, `best_putaways`, and `lowest_xba_allowed` has an explicit `batter` field. "
    "Use THAT batter's name. Do NOT swap in a different batter from elsewhere in the box "
    "score. If the `batter` field is null, describe the pitch without naming a batter.\n"
    "- TOTAL OUTS across multiple pitchers ('three scoreless innings, nine outs', 'eight "
    "outs without a hit'): only assertable from the sum of `pitching_line` IP values for "
    "those pitchers. Convert IP correctly: 1.0 IP = 3 outs, 1.1 IP = 4 outs, 1.2 IP = 5 outs, "
    "etc. (the decimal is THIRDS, not tenths). Do NOT count outs by inning blocks. If math "
    "is required, omit the total and describe each pitcher's line individually.\n"
    "- SAVE / HOLD NUMBERS ('his 12th save', '7th hold of the year'): only assertable when "
    "the pitcher's `decision` field in `boxscore.pitchers` contains the explicit count (e.g., "
    "'SV, 12' or 'H, 7'). A hold is NOT a save. Read the letter before the number.\n"
    "- PLAYER ROLE / POSITION ('pinch-runner', 'pinch-hitter', 'defensive replacement', "
    "'late-inning sub'): only assertable from `boxscore.batters[].position` (e.g., 'PH', "
    "'PR') for that player. A player listed at a fielding position (LF, 2B, etc.) entered "
    "in that role, NOT as a pinch-runner. Do NOT infer roles from when they appeared in "
    "the game.\n"
    "- PITCH ACTION INVENTIONS ('checked his swing', 'attempted a bunt', 'took a borderline "
    "strike', 'shook off the catcher'): the pitch sequence codes in bbref `pitches` "
    "(B=ball, C=called strike, S=swinging strike, F=foul, L=foul bunt or line drive, "
    "X=in play, T=foul tip, * indicates pitch-out adjacent) do NOT unambiguously confirm "
    "any of these biographical narrations. Describe what the play description literally "
    "says; do not invent batter intent or catcher dynamics.\n"
    "- WPA TIMING for a specific moment ('with two outs and a runner on first the Cardinals "
    "were at 80.8% to win'): `stl_wp_after_pct` is the win probability IMMEDIATELY AFTER the "
    "named play (the batter who is listed on that key_swings row). It is NOT the win "
    "probability at a different out / runner state than the one produced by that play. Tie "
    "the percentage to the specific play, not to a different downstream moment.\n"
    "- WPA ARITHMETIC ('a 48.5-point swing from 80.8% to 46.4%'): the pre-play WP must equal "
    "the post-play WP minus the signed delta. If `wpa_delta_pct_stl = -48.5` and "
    "`stl_wp_after_pct = 46.4`, then the pre-play STL WP was 46.4 - (-48.5) = 94.9%, not "
    "80.8%. Verify the arithmetic before stating both endpoints of a swing. If you cannot "
    "verify, state only one anchor (the post-play WP or the delta), not both.\n"
    "- BIOGRAPHICAL / CONTEXTUAL COLOR (calendar dates 'Mother's Day', 'the home opener'; "
    "stadium landmarks 'into the Western Metal Supply building', 'over the Crawford Boxes', "
    "'caromed off Tal's Hill'; weather mood 'a sleepy May afternoon'; crowd reactions 'silenced "
    "the Petco faithful'; off-field references 'with President Biden in the stands'): NONE of "
    "this is in the JSON unless an explicit field carries it. The only color fields available "
    "are `game_context.weather`, `wind`, `attendance`, `linescore_note`, and the play "
    "`description` text. Do NOT add geographic landmarks, holidays, mood phrases, crowd "
    "reactions, or cultural references unless the data block literally contains them. "
    "Bernie Miklasz / Derrick Goold style is allowed in voice and rhythm; it is NOT allowed "
    "as a license to invent setting details.\n"
)


SECTION_INSTRUCTIONS = """## Score and Data for {Month D, YYYY}

REPLACE `{Month D, YYYY}` with the actual game date from POSTGAME DATA's `date` field, formatted as e.g. `May 9, 2026`. Your literal `##` heading should read: `## Score and Data for May 9, 2026`. If POSTGAME DATA is null, use yesterday's date (the date of the off day, NOT the report date) and append "(off day)": `## Score and Data for May 11, 2026 (off day)`.

**OFF-DAY MODE — when POSTGAME DATA is null:**
Skip all box-score / line-score / WPA / Game Analysis / Win Probability Swings subsections. The section is exactly TWO short paragraphs and nothing else:

1. One sentence stating the off day, then one sentence pointing to the next game. Use NEXT GAME DATA values verbatim — never invent. Format:
   > The Cardinals were off yesterday, {weekday, Month D, YYYY of off day}. They play {tomorrow|today|on {weekday, Month D}} {vs.|at} the {opp_short} at {venue}.
   - Use the EXACT `when_phrase` provided below the NEXT GAME DATA block ("tomorrow", "today", or "on {Weekday, Month D}"). Do not improvise — the system computes this from the report date.
   - Use "vs." when `stl_is_home` is true, "at" when false.
2. One sentence naming the probable starters. Format:
   > Probable starters: {stl_probable_pitcher} for St. Louis, {opp_probable_pitcher} for {opp_short}.
   - If either probable is null in NEXT GAME DATA, write "TBD" in that slot.
   - If both are null AND NEXT GAME DATA itself is null, replace this paragraph with: "Next game and probable starters had not posted at publish time."

That is the entire Score and Data section on an off day. Do NOT add Game Analysis, Win Probability Swings, or any other subsection. The rest of the report (Cardinals Notebook, Beat Writer's Verdict, Statcast Highlights, Around the League, Interesting Analysis) follows normally.

**GAME-DAY MODE — when POSTGAME DATA is present**, lead the report with this. Build the section in **this exact order**:

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

**(d) Game Analysis.** Header it `### Game Analysis`. Four to five paragraphs of beat-writer prose, **driven entirely by the POSTGAME DATA block** — no citations to blogs, podcasts, or other expert content in this subsection. The blog/podcast material is for Cardinals Notebook, not the game story.

This is the narrative center of the report. It walks the reader through how the game actually unfolded, with scout-flavored color woven into the prose rather than appended as stat tags. Most sentences should read as plain English. Reach for a metric only when the metric IS the moment. A good worked example: "O'Brien hung the third sinker of the at-bat over the plate, and Castellanos didn't miss. The homer flipped the game." That's a cleaner version of the same beat than: "O'Brien's third 98.5 mph Sinker of the at-bat, the previous two fouled off, ran back over the plate to Castellanos for a 105.2 mph homer and a +48.5% win-probability swing." Same information, but the first reads like a writer and the second reads like a JSON dump. Do not write a separate "Scout Notes" bullet list; that color belongs inside the paragraphs.

Use the gamefeed data sources in this priority order. Every claim must tie to a specific datum:

- **`wpa.key_swings`** — THE narrative spine. Top 6 at-bats by |WPA Δ|, each with batter, pitcher, pitch type, pitch velocity, EV, event, and full play description. Every `wpa_delta_pct_stl` is in **Cardinals perspective**: positive = Cardinals' win probability went UP, negative = Cardinals' win probability went DOWN. A Castellanos walk-off HR for San Diego shows as a negative number for the Cardinals. A Walker HR for St. Louis shows as a positive number. The `stl_wp_after_pct` field is the Cardinals' win probability immediately after that at-bat. Build the game arc around these. A name and outcome is usually enough to carry a sentence; cite the specific pitch type, EV, or WPA delta only when that detail IS the story (a true barrel, an outlier velocity, a single swing that moved win probability by twenty-plus points). The pivot moment of the game earns the full treatment; the others can usually be described in plain English. The Win Probability Swings table below this section will carry the full per-pitch metrics, so the prose does not need to.
- **`scoring_plays`** — chronological scoring sequence with the batter/pitcher/EV/xBA/pitch-velo. Connective tissue between key swings.
- **`game_context.final_play`** — if the game ended on a scoring play (walk-off), open or close with it explicitly.
- **`game_context.linescore_note`** — phrases like "One out when winning run scored" are pure beat-writer color; work them in naturally.
- **`wpa.top_wpa_players`** — cumulative game WPA leaders (any team). Often the right protagonist for the lede or kicker even if their box-score line isn't loudest. Triangulate with `key_swings` for hero/goat.
- **`wpa.last_plays`** — the last 3 plays of the game in chronological order; useful for kicker-paragraph color.
- **`top_performers`** — MLB's own curated standouts. Use the `pitching_line` / `batting_line` strings verbatim (e.g., "5.0 IP, 0 ER, 5 K, 4 BB"). Distinguish Cardinals (`is_stl: true`) from opponents.
- **`game_context.weather` / `wind` / `attendance` / `game_time`** — sprinkle for scene-setting (one mention max — don't make this a weather report).
- **`game_context.abs_challenges`** — note when ABS challenges flipped a call in a leverage spot; reference the player.
- **`statcast_highlights`** — reach for specific EV/xBA/velo/spin numbers when they earn the mention (a barrel, an outlier velocity, a putaway pitch that suppressed contact). Default to description ("Walker's 11th, a no-doubter to dead center") and add a metric only when it adds something the reader couldn't infer from the outcome. Walker's homer doesn't need both EV and xBA in prose; the Statcast Highlights bullets section below carries that.
- **`boxscore.batters` / `boxscore.pitchers`** — context lines (who else was in the lineup, bullpen usage, decisions).

Scout-flavored color is welcome inside the prose: pitch sequences, location reads, count leverage, pitch design observations. Embed it in flowing sentences, not a bulleted appendix. NEVER invent a number. Every velocity, EV, xBA, or WPA value must come straight from POSTGAME DATA. Equally important, and easy to forget: you are not required to use every number that's available. Most batted balls described in the narrative do NOT need their EV stated. Most pitches do NOT need their velo stated. Save the metrics for the moments where the metric is the angle.

**Strict pairing rule.** When a pitcher highlight (top_pitches, top_whiffs, best_putaways, lowest_xba_allowed) names a batter, you may say "Pitcher X retired/whiffed/punched out Batter Y". When the data block has no `batter` field for that pitch, you must NOT pair it with a specific batter name — describe it as "an 86 mph Sweeper drew a .020 xBA flyout" instead of "his 86 mph Sweeper retired Manny Machado".

**Adjective fidelity.** Hit-classification words (line drive, bloop, flare, grounder, lineout, popup) must match the JSON `description` text from scoring_plays or wpa.key_swings. If the description says "line drive", do not call it a "bloop". If the data says "grounds out, shortstop to first", do not call it a chopper.

**Intentional walks.** Only describe a walk as "intentional" if `game_context.intentional_walks` explicitly names that batter (format: "Merrill (by Graceffo).").

**Kicker line — strict rule.** End with one line that closes the game story using ONLY values present in POSTGAME DATA (final score, key WPA delta, a pitch metric, the linescore note). DO NOT mention:
- The upcoming opponent, next series, travel day, or next probable pitcher (that lives in Beat Writer's Verdict).
- Records, season-long stats, multi-game streaks, or any cumulative figure not present in POSTGAME DATA.
- ANY information sourced from blogs, podcasts, or expert content (still no source attribution in this section).

The kicker can be a clean sentence of beat-writer judgment with no numbers at all, as long as it's grounded in what happened (e.g., "A 2-3 loss at Petco, the bullpen one pitch short of holding it."). A score-plus-detail line is also fine when the detail is genuinely the story (e.g., "A 2-3 final, settled when O'Brien's third sinker of the at-bat caught too much plate."). What to avoid: stacking weather, ballpark, attendance, and a stat into one robotic closer. "A 2-1 final on a 74-degree afternoon at American Family Field, decided by a fielding error in the eighth and a 30.0-point Yelich swing on a 93.3 mph Sinker" is the cadence to escape. Better short and true than long and stat-jammed.

If POSTGAME DATA is null (off day), follow the **OFF-DAY MODE** instructions at the top of this section — do NOT write Game Analysis on an off day.

**(e) Win Probability Swings.** Header it `### Win Probability Swings`. Render the top 4-5 plays from POSTGAME DATA's `wpa.key_swings` as a markdown table, in WPA-impact order (largest |Δ| first, which is how the data already arrives). These are the at-bats that *actually moved the game*, with per-pitch context. Skip this whole subsection if `wpa.key_swings` is absent or empty.

```
### Win Probability Swings

| Moment | Δ WP (STL) | Batter (Team) vs Pitcher | Result |
|---|---:|---|---|
| B9 | −48.5% | Nick Castellanos (SD) vs Riley O'Brien | HR on 98.5 mph Sinker, 105.2 mph EV |
| T4 | +21.7% | Jordan Walker (STL) vs Walker Buehler | HR on 76.3 mph Knuckle Curve, 108.3 mph EV |
| T10 | −12.0% | José Fermín (STL) vs Adrian Morejon | Pop Out on 98.8 mph Sinker (rally ends) |
| ... |
```

Δ WP (STL) is the **Cardinals** win-probability change for that at-bat. Pull from `wpa_delta_pct_stl`. Positive = Cardinals' chances went UP. Negative = Cardinals' chances went DOWN. A San Diego HR off the Cardinals shows as a negative number for the Cardinals. A Cardinals HR shows as a positive number. The column header MUST read `Δ WP (STL)`. Format the Result cell as a one-clause description that names the pitch type, pitch velocity, and either EV/outcome or context — pull from `description`, `pitch_type`, `pitch_velo_mph`, and `ev_mph`. Use the original Unicode minus sign `−` for negative deltas (not a hyphen).

The Score and Data section ENDS after the Win Probability Swings table. Statcast Highlights lives in its own H2 section further down the report (after Beat Writer's Verdict). Do NOT include a Statcast Highlights subsection inside Score and Data.

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

## Statcast Highlights

Two clearly-labeled groups (Hitters and Pitchers). Pull from `statcast_highlights`. Skip any bucket that is empty or missing. Each bullet must include the specific numeric values from the data — do NOT round or paraphrase. The expected-value metric is xBA (expected batting average) when present; some legacy data may still use xwOBA — render whichever field actually appears in the data block.

```
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

If a sub-bucket has multiple entries (top 3), list each on its own line. The numbers are the same data the game narrative already cited — this section is the appendix that lets a reader scan the bullets after they've read the prose.

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


def build_prompt(
    today: date,
    content_block: str,
    postgame: dict | None,
    mlb_headlines: list[dict] | None = None,
    analysis_headlines: list[dict] | None = None,
    next_game: dict | None = None,
    off_day_date: date | None = None,
) -> str:
    parts: list[str] = []

    parts.append(
        f"Write the daily St. Louis Cardinals intelligence report for {today.strftime('%B %d, %Y')}.\n\n"
        "Sections (in this exact order, ## level): "
        "Score and Data for {Month D, YYYY} (where the date is the actual game date from POSTGAME DATA), "
        "Cardinals Notebook, Beat Writer's Verdict, Statcast Highlights, Around the League, Interesting Analysis.\n\n"
        "Do NOT add any other sections. No 'Previous Game', no 'MLB Cardinals', no 'MLB News Brief', "
        "no 'Around the Internet', no 'Minor League Cardinals', no 'Sibling Rivalry', no 'Cardinals Corner'. "
        "Six sections only. Statcast Highlights lives as its own ## section between Beat Writer's Verdict "
        "and Around the League — NOT inside Score and Data.\n\n"
    )
    parts.append(SECTION_INSTRUCTIONS)

    parts.append("\n\n---\n\n# POSTGAME DATA (yesterday's MLB Cardinals game)\n\n")
    if postgame:
        parts.append("```json\n")
        parts.append(json.dumps(postgame, indent=2, default=str))
        parts.append("\n```\n")
    else:
        parts.append("`null` — no Cardinals game on the target date (off day or postponed).\n")
        if off_day_date is not None:
            parts.append(
                f"\nOFF-DAY DATE (use this in the Score and Data lede): "
                f"**{off_day_date.strftime('%A, %B %-d, %Y')}** ({off_day_date.isoformat()}).\n"
            )
        parts.append("\n## NEXT GAME DATA (next scheduled Cardinals game)\n\n")
        if next_game:
            parts.append("```json\n")
            parts.append(json.dumps(next_game, indent=2, default=str))
            parts.append("\n```\n")
            try:
                ng_date = date.fromisoformat((next_game.get("date") or "")[:10])
                if ng_date == today + timedelta(days=1):
                    when_phrase = "tomorrow"
                elif ng_date == today:
                    when_phrase = "today"
                else:
                    when_phrase = f"on {ng_date.strftime('%A, %B %-d')}"
                parts.append(f'\nUse the phrase **"{when_phrase}"** for when they play next.\n')
            except (TypeError, ValueError):
                pass
        else:
            parts.append("`null` — no scheduled game found in the next 7 days.\n")

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
        parts.append(
            "_(No analysis headlines available — write 'Quiet day for baseball longform.')_\n"
        )

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


def _is_postponed(postgame: dict | None) -> bool:
    """True when the scheduled game did not happen (rain, suspension, etc.)."""
    if not postgame:
        return False
    status = (postgame.get("status") or "").lower()
    return any(token in status for token in ("postpone", "cancelled", "suspended"))


def _format_blot_title(today: date, postgame: dict | None) -> str:
    """Build the Blot post Title from postgame data.

    Uses the GAME date (yesterday) for the date stamp, not today's report date.
    Off-day titles also stamp the off-day date (yesterday), not the publish
    date — the post is *about* yesterday, not today.

    Examples:
      "@ Padres 2-4 (L) — May 9"
      "vs. Reds 7-3 (W) — May 11"
      "@ Reds (PPD) — May 24"          ← postponed
      "Cardinals — May 11 (off day)"   ← stamps yesterday, not today
    """
    if not postgame:
        off_day = today - timedelta(days=1)
        return f"Cardinals. {off_day.strftime('%B %-d')} (off day)"

    # Pull the actual game date from postgame.date (ISO YYYY-MM-DD); fall back to today.
    try:
        game_date = date.fromisoformat(postgame.get("date") or "")
        date_short = game_date.strftime("%B %-d")
    except (TypeError, ValueError):
        date_short = today.strftime("%B %-d")

    stl_is_home = bool(postgame.get("stl_is_home"))
    if stl_is_home:
        opp_full = postgame.get("away_team") or "Opponent"
        connector = "vs."
    else:
        opp_full = postgame.get("home_team") or "Opponent"
        connector = "@"
    opp_short = opp_full.split()[-1] if opp_full else "Opponent"

    if _is_postponed(postgame):
        return f"{connector} {opp_short} (PPD) — {date_short}"

    ls = postgame.get("line_score") or {}
    totals = ls.get("totals") or {}
    if stl_is_home:
        stl_r = ((totals.get("home") or {}).get("R")) or 0
        opp_r = ((totals.get("away") or {}).get("R")) or 0
    else:
        stl_r = ((totals.get("away") or {}).get("R")) or 0
        opp_r = ((totals.get("home") or {}).get("R")) or 0

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
    venue = postgame.get("venue") or ""
    if _is_postponed(postgame):
        stl_is_home = bool(postgame.get("stl_is_home"))
        opp_full = (
            postgame.get("away_team") if stl_is_home else postgame.get("home_team")
        ) or "Opponent"
        base = f"Cardinals vs {opp_full} postponed"
        return f"{base} at {venue}." if venue else f"{base}."
    matchup = postgame.get("matchup") or ""
    result = postgame.get("result") or ""
    # Result is like "St. Louis Cardinals 2, San Diego Padres 4 (STL L)"
    # Strip the (STL X) suffix and shorten "St. Louis Cardinals" → "Cardinals"
    cleaned = re.sub(r"\s*\(STL [WLT]\)\s*$", "", result).replace(
        "St. Louis Cardinals", "Cardinals"
    )
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
    # Linkify blogs/podcasts AFTER players so existing player [name](url) spans
    # are skipped by the source-name regex.
    source_articles = load_source_articles(today)
    linked = linkify_sources(linked, SOURCE_HOMEPAGES, source_articles, today)
    title = _format_blot_title(today, postgame)
    summary = _extract_summary(postgame)

    # Blot metadata header. Blank line separates metadata from post body.
    # Thumbnail points at the OG banner generated below; setting it explicitly
    # gives Blot's template a reliable hook for archive previews + og:image
    # rather than relying on "first image >64px" heuristic. Comments disabled
    # site-wide. Tags retest: Blot supports comma-separated metadata tags;
    # earlier omission was a template render bug that may be resolved.
    banner_name = f"_{today.isoformat()}-cardinals-daily.png"
    blot_header = (
        f"Title: {title}\n"
        f"Date: {today.isoformat()}\n"
        f"Summary: {summary}\n"
        f"Link: cardinals-daily-{today.isoformat()}\n"
        f"Tags: Cardinals, Game Recap\n"
        f"Thumbnail: {banner_name}\n"
        f"Comments: No\n"
        "\n"
    )

    # Strip the leading H1 (whatever it says) — Blot derives the title from
    # the metadata above. Old regex was too narrow; this matches any first H1.
    body = re.sub(r"^\s*#\s+.+?\n+", "", linked.lstrip(), count=1)

    # Generate the per-post OG banner and embed it as the first inline image.
    # Underscore-prefixed filename keeps Blot from publishing the PNG as its
    # own standalone photo post (per blot.im/how/files/images) — it stays a
    # referenced asset of the .md post. Sibling placement in Posts/ lets Blot
    # resolve the relative path and pick it up as {{#thumbnail.large}}, which
    # lights up the iMessage / social rich-card preview via the og:image tags
    # in head.html. Wrapped: a banner failure never blocks the publish.
    try:
        # On a game day the banner stamps the game date; on an off day it
        # stamps the off-day date (yesterday) — the post is *about* yesterday,
        # not the publish date.
        game_date = today - timedelta(days=1)
        if postgame and postgame.get("date"):
            try:
                game_date = date.fromisoformat(postgame["date"])
            except ValueError:
                pass
        generate_og_banner(postgame, BLOT_POSTS_DIR / banner_name, game_date)
        body = f"![Cardinals Daily — {title}]({banner_name})\n\n{body}"
        log.info("Generated OG banner: %s", banner_name)
    except Exception as exc:  # noqa: BLE001 — banner is enhancement-only
        log.warning("OG banner generation failed (%s); publishing without it", exc)

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
    source_articles = load_source_articles(today)
    linked = linkify_sources(linked, SOURCE_HOMEPAGES, source_articles, today)
    sources = build_sources_section(items)

    frontmatter = (
        "---\n"
        f'title: "Cardinals Daily — {today.strftime("%B %d, %Y")}"\n'
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


def run(
    force: bool = False,
    days: int = CONTENT_WINDOW_DAYS,
    dry_run: bool = False,
    report_date: date | None = None,
    skip_factcheck: bool = False,
) -> None:
    today = report_date or date.today()
    out_path = ANALYSIS_DIR / f"{today.isoformat()}_{REPORT_SLUG}.md"

    if out_path.exists() and not force and not dry_run:
        log.info(
            "Today's Cardinals report already exists at %s (use --force to regenerate)", out_path
        )
        return

    target_postgame_date = today - timedelta(days=1)
    log.info("Fetching postgame data for %s", target_postgame_date.isoformat())
    postgame = None
    try:
        postgame = get_cardinals_postgame(target_postgame_date)
    except Exception as e:
        log.warning("Postgame fetch failed: %s — proceeding without postgame data", e)

    # When yesterday was an off day, the report's Score and Data section
    # leans on the next scheduled game (date, opponent, probable starters)
    # instead of a boxscore. Look forward from today so we skip yesterday's
    # blank slate but include any same-day game posted later in the morning.
    next_game = None
    off_day_date = target_postgame_date if postgame is None else None
    if postgame is None:
        log.info("Off day detected — fetching next scheduled Cardinals game")
        try:
            next_game = get_cardinals_next_game(today)
        except Exception as e:
            log.warning("Next-game fetch failed: %s — off-day lede will be generic", e)

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

    user_message = build_prompt(
        today,
        content_block,
        postgame,
        mlb_headlines,
        analysis_headlines,
        next_game=next_game,
        off_day_date=off_day_date,
    )

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
        len(text.split()),
        in_toks,
        out_toks,
        stop,
    )

    # ----- Fact-check the Score and Data section -----
    # The narrative runs on POSTGAME DATA only; the fact-checker compares every
    # numeric / factual claim against the JSON + bbref PBP. On fail, we apply a
    # SURGICAL EDIT retry (only the flagged phrases get touched) and re-check.
    # We keep iterating up to MAX_FACTCHECK_ATTEMPTS before quarantining — the
    # 3 AM cron tolerates longer runtime in exchange for getting a clean post
    # published automatically rather than landing in factcheck_failed/ for
    # manual intervention. `--skip-factcheck` bypasses the whole loop.
    if skip_factcheck:
        log.warning("--skip-factcheck flag set, bypassing verification.")
    elif postgame is None:
        # Off-day Score and Data has no game claims to verify — it is a fixed
        # two-paragraph lede built from NEXT GAME DATA. Running the fact-checker
        # against `null` postgame would (correctly) flag the forward-looking
        # next-game / probable-starter lines as fabrication. Skip the loop.
        log.info("Off-day report (no postgame); skipping Score and Data fact-check.")
    else:
        attempt = 0
        while True:
            attempt += 1
            factcheck = factcheck_score_and_data(
                extract_score_and_data(text) or "",
                postgame,
            )
            if factcheck.passed:
                log.info("Fact-check PASSED on attempt %d.", attempt)
                break

            log.warning(
                "Fact-check FAILED on attempt %d. %d issues.",
                attempt,
                len(factcheck.issues),
            )
            for i in factcheck.issues:
                log.warning("  - [%s] %s — %s", i.category, i.claim, i.why_suspect)

            if attempt >= MAX_FACTCHECK_ATTEMPTS:
                log.error(
                    "Hit MAX_FACTCHECK_ATTEMPTS (%d). Quarantining.",
                    MAX_FACTCHECK_ATTEMPTS,
                )
                _quarantine_failed_report(today, text, in_toks, out_toks, factcheck)
                return

            log.info(
                "Applying surgical edits (attempt %d → %d)...",
                attempt,
                attempt + 1,
            )
            retry_message = _build_retry_message(text, postgame, factcheck)
            try:
                text2, in2, out2, _stop2 = _invoke_claude_cli(
                    MODEL,
                    SYSTEM_PROMPT,
                    retry_message,
                )
            except Exception as e:
                log.error("Retry edit failed: %s. Quarantining.", e)
                _quarantine_failed_report(today, text, in_toks, out_toks, factcheck)
                return

            if not text2:
                log.error("Empty retry response. Quarantining.")
                _quarantine_failed_report(today, text, in_toks, out_toks, factcheck)
                return

            text = text2
            in_toks += in2
            out_toks += out2

    player_links = load_player_links(DB_PATH)
    out = write_report(today, text, items, in_toks, out_toks, player_links)
    cost = (in_toks * 5 + out_toks * 25) / 1_000_000
    log.info("Done. Wrote %s (~$%.2f subscription quota, not billed)", out, cost)

    # Publish to Blot. Non-fatal — if Dropbox is unmounted or path missing, we log and move on.
    try:
        _publish_to_blot(today, text, player_links, postgame=postgame)
    except Exception as e:
        log.warning("Blot publish failed (non-fatal): %s", e)


def _build_retry_message(previous_draft: str, postgame: dict | None, factcheck) -> str:
    """Build a SURGICAL-EDIT retry message.

    Sends Claude the previous draft verbatim plus a list of specific phrase-level
    issues, and asks it to return the full draft with ONLY those phrases changed.
    This avoids the full-regeneration retry's two failure modes: wasted tokens
    rewriting paragraphs that already passed, and Claude introducing fresh
    inferences in the rewrite that the prior draft didn't have.
    """
    issue_lines = []
    for i in factcheck.issues:
        line = f'  - Claim: "{i.claim}"\n    Why suspect: {i.why_suspect}'
        if i.json_value_if_close:
            line += f"\n    Actual value in JSON: {i.json_value_if_close}"
        issue_lines.append(line)

    postgame_json = (
        json.dumps(postgame, indent=2, default=str)
        if postgame is not None
        else "null  // no game on the target date"
    )

    return (
        "You are applying SURGICAL EDITS to a previously generated Cardinals daily report.\n\n"
        "POSTGAME DATA (for reference, to look up correct values):\n\n"
        f"```json\n{postgame_json}\n```\n\n"
        "PREVIOUS DRAFT (full markdown of the report):\n\n"
        "```markdown\n"
        f"{previous_draft}\n"
        "```\n\n"
        "FACT-CHECK ISSUES TO FIX:\n\n" + "\n\n".join(issue_lines) + "\n\n"
        "INSTRUCTIONS:\n"
        "- Output the FULL report markdown verbatim, with ONLY the flagged phrases edited.\n"
        "- For each flagged claim:\n"
        "    (a) If the actual JSON value is provided above, replace the wrong value with that value.\n"
        "    (b) If no JSON value exists, REMOVE the claim entirely (delete the phrase or sentence).\n"
        "    Choose the option that produces the cleanest sentence.\n"
        "- Do NOT rewrite paragraphs that contain no flagged claims. Leave them character-for-character identical.\n"
        "- Do NOT add new sentences, new prose, or new claims to compensate for removed content.\n"
        "- Do NOT touch the frontmatter, section headers, tables, or bullet lists unless a flagged claim lives inside them.\n"
        "- Preserve every existing markdown link, italic citation, table row, and bullet point unless a flagged claim is inside it.\n"
        "- Output the entire corrected report, including the leading H1 and all sections, in one block of markdown. No commentary, no surrounding prose, just the corrected report.\n"
    )


def _quarantine_failed_report(
    today: date, text: str, in_toks: int, out_toks: int, factcheck
) -> None:
    """Move a fact-check-failed report out of the normal pipeline path.

    Writes the failing MD plus a sibling `.factcheck.json` log to
    FACTCHECK_FAILED_DIR so it is preserved for review but excluded from the
    glob the downstream bash pipeline uses to find today's reports.
    """
    FACTCHECK_FAILED_DIR.mkdir(parents=True, exist_ok=True)
    failed_md = FACTCHECK_FAILED_DIR / f"{today.isoformat()}_{REPORT_SLUG}.md"
    failed_md.write_text(text, encoding="utf-8")
    failed_log = FACTCHECK_FAILED_DIR / f"{today.isoformat()}_{REPORT_SLUG}.factcheck.json"
    failed_log.write_text(
        json.dumps(factcheck.to_dict(), indent=2),
        encoding="utf-8",
    )
    log.error(
        "Fact-check FAILED after retry — %d issues remain. Report quarantined to %s",
        len(factcheck.issues),
        failed_md,
    )
    log.error("Issues:\n%s", factcheck.issue_summary())

    # Best-effort macOS notification so the user notices before the 4 AM verifier.
    try:
        import subprocess

        msg = f"{len(factcheck.issues)} fact-check issues — quarantined to factcheck_failed/"
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{msg}" with title "Cardinals report BLOCKED" '
                f'subtitle "{today.isoformat()} — see {failed_log.name}"',
            ],
            check=False,
            timeout=5,
        )
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Cardinals intelligence report")
    parser.add_argument("--force", action="store_true", help="Regenerate even if today's exists")
    parser.add_argument("--dry-run", action="store_true", help="Preview prompt without API call")
    parser.add_argument(
        "--days",
        type=int,
        default=CONTENT_WINDOW_DAYS,
        help=f"Content lookback window in days (default: {CONTENT_WINDOW_DAYS})",
    )
    parser.add_argument(
        "--date",
        dest="report_date",
        type=date.fromisoformat,
        default=None,
        help="Override report date (YYYY-MM-DD). The covered game is this date minus one.",
    )
    parser.add_argument(
        "--skip-factcheck",
        action="store_true",
        help="Bypass the Opus 4.8 fact-check pass (emergency / debug only).",
    )
    args = parser.parse_args()
    run(
        force=args.force,
        days=args.days,
        dry_run=args.dry_run,
        skip_factcheck=args.skip_factcheck,
        report_date=args.report_date,
    )


if __name__ == "__main__":
    main()
