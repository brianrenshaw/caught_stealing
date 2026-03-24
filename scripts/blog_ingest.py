#!/usr/bin/env python3
"""Blog RSS feed ingester for fantasy baseball content.

Fetches articles from FanGraphs Blog and Pitcher List RSS feeds,
extracts full content, and saves as markdown files with YAML frontmatter.

Usage:
    uv run python -m scripts.blog_ingest                    # fetch new articles
    uv run python -m scripts.blog_ingest --days 7           # last 7 days only
    uv run python -m scripts.blog_ingest --max-articles 10  # limit per feed
    uv run python -m scripts.blog_ingest --list-feeds       # show configured feeds
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import httpx
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = PROJECT_ROOT / "data" / "content" / "blogs"
MANIFEST_PATH = PROJECT_ROOT / "data" / "content" / "manifest.json"

RSS_FEEDS = {
    "fangraphs": {
        "name": "FanGraphs Blog",
        "url": "https://blogs.fangraphs.com/feed/",
        "type": "rss",
    },
    "pitcherlist": {
        "name": "Pitcher List",
        "url": "https://pitcherlist.com/feed",
        "type": "rss",
    },
    "rotowire": {
        "name": "RotoWire MLB News",
        "url": "https://www.rotowire.com/rss/news.php?sport=MLB",
        "type": "rss",
    },
}

REQUEST_DELAY = 1.0  # seconds between HTTP requests
REQUEST_TIMEOUT = 30  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def slugify(text: str, max_len: int = 60) -> str:
    """Convert text to filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len]


def parse_entry_date(entry: dict) -> datetime | None:
    """Extract published date from a feed entry."""
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def extract_text_from_html(html: str) -> str:
    """Strip HTML tags and return clean text."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove script/style elements
    for tag in soup(["script", "style"]):
        tag.decompose()

    return soup.get_text(separator="\n", strip=True)


def html_to_markdown(html: str) -> str:
    """Convert HTML content to simple markdown."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove script/style
    for tag in soup(["script", "style"]):
        tag.decompose()

    # Convert common elements
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        level = int(h.name[1])
        h.replace_with(f"\n{'#' * level} {h.get_text(strip=True)}\n")

    for p in soup.find_all("p"):
        p.replace_with(f"\n{p.get_text(strip=True)}\n")

    for li in soup.find_all("li"):
        li.replace_with(f"- {li.get_text(strip=True)}\n")

    for strong in soup.find_all(["strong", "b"]):
        strong.replace_with(f"**{strong.get_text(strip=True)}**")

    for em in soup.find_all(["em", "i"]):
        em.replace_with(f"*{em.get_text(strip=True)}*")

    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        href = a.get("href", "")
        if href and text:
            a.replace_with(f"[{text}]({href})")

    text = soup.get_text(separator="\n")
    # Collapse excessive newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_manifest() -> dict:
    """Load or create the content manifest."""
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"blogs": {}, "transcripts": {}}


def save_manifest(manifest: dict) -> None:
    """Save the content manifest."""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=str))


# ---------------------------------------------------------------------------
# Feed processing
# ---------------------------------------------------------------------------


def fetch_feed(feed_key: str, feed_config: dict) -> list[dict]:
    """Parse an RSS feed and return entries.

    Uses httpx to download the feed (avoids macOS SSL issues with urllib),
    then parses the content with feedparser.
    """
    log.info("Fetching feed: %s (%s)", feed_config["name"], feed_config["url"])
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(feed_config["url"])
            resp.raise_for_status()
        feed = feedparser.parse(resp.text)
    except httpx.HTTPError as e:
        log.error("Failed to fetch feed %s: %s", feed_key, e)
        return []

    if feed.bozo and not feed.entries:
        log.error("Failed to parse feed %s: %s", feed_key, feed.bozo_exception)
        return []

    log.info("  Found %d entries", len(feed.entries))
    return feed.entries


def fetch_full_article(url: str) -> str | None:
    """Fetch full article HTML from URL and extract main content."""
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Try common article content selectors
        content = None
        for selector in [
            "article",
            ".post-content",
            ".entry-content",
            ".article-content",
            ".blog-content",
            "main",
        ]:
            content = soup.select_one(selector)
            if content:
                break

        if content:
            return str(content)
        return None

    except (httpx.HTTPError, Exception) as e:
        log.warning("  Failed to fetch full article %s: %s", url, e)
        return None


def process_entry(
    feed_key: str,
    entry: dict,
    manifest: dict,
    fetch_full: bool = True,
) -> dict | None:
    """Process a single feed entry into a markdown file.

    Returns metadata dict if saved, None if skipped.
    """
    title = entry.get("title", "Untitled")
    link = entry.get("link", "")
    pub_date = parse_entry_date(entry)

    if not pub_date:
        pub_date = datetime.now(timezone.utc)

    date_str = pub_date.strftime("%Y-%m-%d")
    slug = slugify(title)
    filename = f"{date_str}_{feed_key}_{slug}.md"

    # Skip if already ingested
    if filename in manifest.get("blogs", {}):
        return None

    # Get content - prefer full article, fall back to feed content
    content_html = ""
    if fetch_full and link:
        time.sleep(REQUEST_DELAY)
        full_html = fetch_full_article(link)
        if full_html:
            content_html = full_html

    if not content_html:
        # Use feed content (summary or content field)
        content_html = entry.get("content", [{}])[0].get("value", "") if entry.get(
            "content"
        ) else entry.get("summary", "")

    content_md = html_to_markdown(content_html)
    plain_text = extract_text_from_html(content_html)

    # Build frontmatter
    categories = [t.get("term", "") for t in entry.get("tags", [])]
    author = entry.get("author", "")

    frontmatter = f"""---
title: "{title.replace('"', '\\"')}"
source: {feed_key}
source_name: {RSS_FEEDS[feed_key]["name"]}
url: {link}
date: {pub_date.isoformat()}
author: {author}
categories: {json.dumps(categories)}
ingested_at: {datetime.now(timezone.utc).isoformat()}
---"""

    file_content = f"{frontmatter}\n\n# {title}\n\n{content_md}"

    # Save file
    filepath = CONTENT_DIR / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(file_content, encoding="utf-8")

    metadata = {
        "title": title,
        "source": feed_key,
        "url": link,
        "date": pub_date.isoformat(),
        "author": author,
        "categories": categories,
        "filename": filename,
        "word_count": len(plain_text.split()),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }

    log.info("  Saved: %s (%d words)", filename, metadata["word_count"])
    return metadata


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(
    days: int = 3,
    max_articles: int = 20,
    feeds: list[str] | None = None,
    fetch_full: bool = True,
) -> None:
    """Main ingestion loop."""
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()

    if "blogs" not in manifest:
        manifest["blogs"] = {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    feed_keys = feeds or list(RSS_FEEDS.keys())
    total_saved = 0

    for feed_key in feed_keys:
        if feed_key not in RSS_FEEDS:
            log.warning("Unknown feed: %s (skipping)", feed_key)
            continue

        feed_config = RSS_FEEDS[feed_key]
        entries = fetch_feed(feed_key, feed_config)
        saved_count = 0

        for entry in entries:
            if saved_count >= max_articles:
                log.info("  Reached max articles (%d) for %s", max_articles, feed_key)
                break

            pub_date = parse_entry_date(entry)
            if pub_date and pub_date < cutoff:
                continue

            result = process_entry(feed_key, entry, manifest, fetch_full=fetch_full)
            if result:
                manifest["blogs"][result["filename"]] = result
                saved_count += 1
                total_saved += 1

    save_manifest(manifest)
    log.info("Done. Saved %d new articles.", total_saved)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest fantasy baseball blog RSS feeds")
    parser.add_argument(
        "--days", type=int, default=3, help="Fetch articles from the last N days (default: 3)"
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=20,
        help="Max articles per feed (default: 20)",
    )
    parser.add_argument(
        "--feeds",
        nargs="+",
        choices=list(RSS_FEEDS.keys()),
        help="Specific feeds to fetch (default: all)",
    )
    parser.add_argument(
        "--no-full-fetch",
        action="store_true",
        help="Skip fetching full article HTML (use RSS content only)",
    )
    parser.add_argument(
        "--list-feeds", action="store_true", help="List configured feeds and exit"
    )
    args = parser.parse_args()

    if args.list_feeds:
        print("Configured RSS feeds:")
        for key, config in RSS_FEEDS.items():
            print(f"  {key}: {config['name']} ({config['url']})")
        return

    run(
        days=args.days,
        max_articles=args.max_articles,
        feeds=args.feeds,
        fetch_full=not args.no_full_fetch,
    )


if __name__ == "__main__":
    main()
