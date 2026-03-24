#!/usr/bin/env python3
"""Podcast downloader for fantasy baseball content.

Downloads recent podcast episodes from RSS feeds and places them in a
watch folder for MacWhisper to auto-transcribe. Writes a JSON metadata
sidecar alongside each audio file so the collector script can later
wrap transcripts with proper frontmatter (episode date, title, source, etc.).

Usage:
    uv run python -m scripts.podcast_transcriber                     # download new episodes
    uv run python -m scripts.podcast_transcriber --days 7            # last 7 days
    uv run python -m scripts.podcast_transcriber --max-episodes 3    # limit per feed
    uv run python -m scripts.podcast_transcriber --list-feeds        # show configured feeds

MacWhisper setup:
    1. Watch folder:  data/content/audio/pending/
    2. Output format: .txt
    3. Output folder: data/content/audio/transcribed/
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PENDING_DIR = PROJECT_ROOT / "data" / "content" / "audio" / "pending"
TRANSCRIBED_DIR = PROJECT_ROOT / "data" / "content" / "audio" / "transcribed"
MANIFEST_PATH = PROJECT_ROOT / "data" / "content" / "manifest.json"

load_dotenv(PROJECT_ROOT / ".env")

PODCAST_FEEDS = {
    "cbs_fantasy_baseball": {
        "name": "Fantasy Baseball Today (CBS)",
        "url": "https://feeds.megaphone.fm/CBS6735868419",
    },
    "fantasypros_baseball": {
        "name": "FantasyPros Baseball Podcast",
        "url": (
            "https://www.omnycontent.com/d/playlist/"
            "e73c998e-6e60-432f-8610-ae210140c5b1/"
            "03db435f-86aa-4395-95a3-b2d70144b868/"
            "a32aaa57-276f-4ebd-af98-b2d70144b87c/podcast.rss"
        ),
    },
    "locked_on_fantasy_baseball": {
        "name": "Locked On Fantasy Baseball",
        "url": "https://pdrl.fm/72f472/feeds.simplecast.com/4vzt_3en",
    },
    "in_this_league": {
        "name": "In This League Fantasy Baseball",
        "url": "https://www.spreaker.com/show/3691391/episodes/feed",
    },
}

REQUEST_TIMEOUT = 120

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


def get_audio_url(entry: dict) -> str | None:
    """Extract audio enclosure URL from a feed entry."""
    for enclosure in entry.get("enclosures", []):
        enc_type = enclosure.get("type", "")
        if "audio" in enc_type or enclosure.get("href", "").endswith(".mp3"):
            return enclosure.get("href")

    for link in entry.get("links", []):
        if link.get("type", "").startswith("audio/") or link.get("href", "").endswith(
            ".mp3"
        ):
            return link.get("href")

    return None


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
# MacWhisper
# ---------------------------------------------------------------------------

MACWHISPER_BUNDLE_ID = "com.goodsnooze.MacWhisper"


def ensure_macwhisper_running() -> None:
    """Open MacWhisper if it's not already running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "MacWhisper"],
            capture_output=True,
        )
        if result.returncode != 0:
            log.info("Opening MacWhisper...")
            subprocess.run(
                ["open", "-b", MACWHISPER_BUNDLE_ID],
                check=True,
            )
        else:
            log.info("MacWhisper is already running.")
    except Exception as e:
        log.warning("Could not launch MacWhisper: %s", e)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_episode(
    feed_key: str,
    entry: dict,
    pub_date: datetime,
) -> Path | None:
    """Download a podcast episode into the pending/ folder for MacWhisper.

    Also writes a .json metadata sidecar with the same stem.
    """
    audio_url = get_audio_url(entry)
    if not audio_url:
        log.warning("  No audio URL found for: %s", entry.get("title", "Unknown"))
        return None

    title = entry.get("title", "Untitled")
    date_str = pub_date.strftime("%Y-%m-%d")
    slug = slugify(title)
    stem = f"{date_str}_{feed_key}_{slug}"
    audio_path = PENDING_DIR / f"{stem}.mp3"
    meta_path = PENDING_DIR / f"{stem}.json"

    # Skip if already in pending, transcribed, or in manifest
    if audio_path.exists() or (TRANSCRIBED_DIR / f"{stem}.txt").exists():
        log.info("  Already queued/transcribed: %s", stem)
        return audio_path

    log.info("  Downloading: %s", title)
    log.info("    URL: %s", audio_url[:100])

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            with client.stream("GET", audio_url) as resp:
                resp.raise_for_status()

                audio_path.parent.mkdir(parents=True, exist_ok=True)
                downloaded = 0
                with open(audio_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                        downloaded += len(chunk)

                log.info("    Downloaded: %.1f MB", downloaded / (1024 * 1024))

        # Write metadata sidecar for the collector
        description = ""
        if entry.get("summary"):
            from bs4 import BeautifulSoup

            description = BeautifulSoup(entry["summary"], "html.parser").get_text(
                strip=True
            )

        metadata = {
            "title": title,
            "source": feed_key,
            "source_name": PODCAST_FEEDS[feed_key]["name"],
            "url": entry.get("link", ""),
            "date": pub_date.isoformat(),
            "duration": entry.get("itunes_duration", ""),
            "description": description,
            "audio_file": audio_path.name,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        return audio_path

    except (httpx.HTTPError, OSError) as e:
        log.error("    Download failed: %s", e)
        if audio_path.exists():
            audio_path.unlink()
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(
    days: int = 3,
    max_episodes: int = 5,
    feeds: list[str] | None = None,
) -> None:
    """Download new episodes into the MacWhisper watch folder."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIBED_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    feed_keys = feeds or list(PODCAST_FEEDS.keys())
    total_downloaded = 0

    for feed_key in feed_keys:
        if feed_key not in PODCAST_FEEDS:
            log.warning("Unknown feed: %s (skipping)", feed_key)
            continue

        feed_config = PODCAST_FEEDS[feed_key]
        log.info("Fetching feed: %s", feed_config["name"])
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(feed_config["url"])
                resp.raise_for_status()
            feed = feedparser.parse(resp.text)
        except httpx.HTTPError as e:
            log.error("Failed to fetch feed %s: %s", feed_key, e)
            continue

        if feed.bozo and not feed.entries:
            log.error("Failed to parse feed %s: %s", feed_key, feed.bozo_exception)
            continue

        log.info("  Found %d entries", len(feed.entries))
        episode_count = 0

        for entry in feed.entries:
            if episode_count >= max_episodes:
                log.info("  Reached max episodes (%d) for %s", max_episodes, feed_key)
                break

            pub_date = parse_entry_date(entry)
            if not pub_date:
                continue
            if pub_date < cutoff:
                continue

            title = entry.get("title", "Untitled")
            date_str = pub_date.strftime("%Y-%m-%d")
            slug = slugify(title)
            transcript_filename = f"{date_str}_{feed_key}_{slug}.md"

            # Skip if already in final transcripts
            if transcript_filename in manifest.get("transcripts", {}):
                log.info("  Already processed: %s", title)
                continue

            audio_path = download_episode(feed_key, entry, pub_date)
            if audio_path:
                total_downloaded += 1
                episode_count += 1

    # Ensure MacWhisper is running so it picks up new files
    if total_downloaded > 0:
        ensure_macwhisper_running()

    log.info("Done. Downloaded %d new episodes to pending/.", total_downloaded)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download fantasy baseball podcasts for MacWhisper transcription"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=3,
        help="Fetch episodes from the last N days (default: 3)",
    )
    parser.add_argument(
        "--max-episodes",
        type=int,
        default=5,
        help="Max episodes per feed (default: 5)",
    )
    parser.add_argument(
        "--feeds",
        nargs="+",
        choices=list(PODCAST_FEEDS.keys()),
        help="Specific feeds to process (default: all)",
    )
    parser.add_argument(
        "--list-feeds",
        action="store_true",
        help="List configured podcast feeds and exit",
    )
    args = parser.parse_args()

    if args.list_feeds:
        print("Configured podcast feeds:")
        for key, config in PODCAST_FEEDS.items():
            print(f"  {key}: {config['name']}")
            print(f"    {config['url']}")
        print(f"\nPending folder (MacWhisper watch): {PENDING_DIR}")
        print(f"Transcribed folder (MacWhisper output): {TRANSCRIBED_DIR}")
        return

    run(
        days=args.days,
        max_episodes=args.max_episodes,
        feeds=args.feeds,
    )


if __name__ == "__main__":
    main()
