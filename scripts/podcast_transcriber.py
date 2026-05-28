#!/usr/bin/env python3
"""Podcast downloader + transcriber for fantasy baseball content.

Two-phase pipeline, runs synchronously per invocation:

1. **Download** new episodes from configured RSS feeds into ``pending/`` as
   ``.mp3`` + ``.json`` metadata sidecar.
2. **Transcribe** every ``.mp3`` in ``pending/`` that has a matching sidecar
   via the MacWhisper CLI (``mw transcribe``), wrap stdout in markdown with
   YAML frontmatter, write to ``data/content/transcripts/``, and clean up
   the audio + sidecar.

The transcribe phase sweeps the whole ``pending/`` directory, so episodes
left over from a previous failed run get picked up automatically.

Usage:
    uv run python -m scripts.podcast_transcriber                     # download + transcribe
    uv run python -m scripts.podcast_transcriber --days 7            # last 7 days
    uv run python -m scripts.podcast_transcriber --max-episodes 3    # limit per feed
    uv run python -m scripts.podcast_transcriber --transcribe-only   # skip download, drain pending/
    uv run python -m scripts.podcast_transcriber --keep-audio        # keep .mp3 after transcribing
    uv run python -m scripts.podcast_transcriber --list-feeds        # show configured feeds

Requirements:
    - MacWhisper installed and running (CLI talks to the running app).
    - MacWhisper CLI installed at /usr/local/bin/mw
      (MacWhisper → Settings → Advanced → Install Command-Line Tool).
    - Active transcription model selected (check with ``mw models list``).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
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
TRANSCRIPT_DIR = PROJECT_ROOT / "data" / "content" / "transcripts"
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
    # Cardinals-specific feeds (used by scripts.cardinals_daily_report)
    "locked_on_cardinals": {
        "name": "Locked On St. Louis Cardinals",
        "url": "https://pdrl.fm/3dd3e1/feeds.simplecast.com/tfRqEPHw",
    },
    "walton_and_reis": {
        "name": "Wednesday With Walton and Reis of The Cardinal Nation",
        "url": "https://anchor.fm/s/10c22ea54/podcast/rss",
    },
    "bschaeff_daily": {
        "name": "B-Schaeff Daily",
        "url": "https://anchor.fm/s/12f52af0/podcast/rss",
    },
}

REQUEST_TIMEOUT = 120
TRANSCRIBE_TIMEOUT = 3600  # 1 hour per episode; anything longer is anomalous

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
        if link.get("type", "").startswith("audio/") or link.get("href", "").endswith(".mp3"):
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
MW_CLI = shutil.which("mw") or "/usr/local/bin/mw"


def ensure_macwhisper_running() -> None:
    """Open MacWhisper if it's not already running. The `mw` CLI talks to the app."""
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
            # Give the app a few seconds to fully start before the first CLI call
            import time

            time.sleep(5)
        else:
            log.info("MacWhisper is already running.")
    except Exception as e:
        log.warning("Could not launch MacWhisper: %s", e)


def transcribe_audio(audio_path: Path) -> str | None:
    """Run `mw transcribe` on an audio file. Returns the transcript text or None on failure."""
    if not Path(MW_CLI).exists():
        log.error(
            "    `mw` CLI not found at %s. Install via MacWhisper → Settings → Advanced.",
            MW_CLI,
        )
        return None

    try:
        result = subprocess.run(
            [MW_CLI, "transcribe", str(audio_path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=TRANSCRIBE_TIMEOUT,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        log.error("    mw transcribe timed out after %ds: %s", TRANSCRIBE_TIMEOUT, audio_path.name)
        return None
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "")[:500]
        log.error("    mw transcribe failed (exit %d): %s", e.returncode, stderr)
        return None


def build_markdown(stem: str, transcript_text: str, metadata: dict) -> str:
    """Wrap a transcript with YAML frontmatter, mirroring the old collector format."""
    title = metadata.get("title") or stem.replace("-", " ").title()
    source = metadata.get("source", "unknown")
    source_name = metadata.get("source_name", source.replace("_", " ").title())
    url = metadata.get("url", "")
    episode_date = metadata.get("date", "")
    duration = metadata.get("duration", "")
    description = metadata.get("description", "")
    audio_file = metadata.get("audio_file", f"{stem}.mp3")
    word_count = len(transcript_text.split())

    safe_title = title.replace('"', '\\"')
    frontmatter = (
        "---\n"
        f'title: "{safe_title}"\n'
        f"source: {source}\n"
        f"source_name: {source_name}\n"
        f"url: {url}\n"
        f"date: {episode_date}\n"
        f'duration: "{duration}"\n'
        f"audio_file: {audio_file}\n"
        f"word_count: {word_count}\n"
        f"ingested_at: {datetime.now(timezone.utc).isoformat()}\n"
        "---"
    )

    body = f"\n\n# {title}\n\n"
    if description:
        body += f"## Episode Description\n\n{description}\n\n"
    body += f"## Transcript\n\n{transcript_text}\n"
    return frontmatter + body


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_episode(
    feed_key: str,
    entry: dict,
    pub_date: datetime,
) -> Path | None:
    """Download a podcast episode into the pending/ folder.

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

    # Skip if already in pending or already turned into a final transcript
    if audio_path.exists() or (TRANSCRIPT_DIR / f"{stem}.md").exists():
        log.info("  Already queued/transcribed: %s", stem)
        return audio_path if audio_path.exists() else None

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

        description = ""
        if entry.get("summary"):
            from bs4 import BeautifulSoup

            description = BeautifulSoup(entry["summary"], "html.parser").get_text(strip=True)

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
# Transcribe phase
# ---------------------------------------------------------------------------


def transcribe_pending(keep_audio: bool = False) -> int:
    """Transcribe every .mp3 in pending/ that has a matching .json sidecar.

    Writes wrapped markdown to TRANSCRIPT_DIR, updates the manifest, and
    cleans up the audio + sidecar on success. Returns the count of episodes
    successfully transcribed.
    """
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest()
    manifest.setdefault("transcripts", {})

    audio_files = sorted(
        p for p in PENDING_DIR.glob("*.mp3") if (PENDING_DIR / f"{p.stem}.json").exists()
    )

    if not audio_files:
        log.info("No pending audio to transcribe.")
        return 0

    log.info("Transcribing %d pending episode(s)...", len(audio_files))
    transcribed = 0

    for audio_path in audio_files:
        stem = audio_path.stem
        md_filename = f"{stem}.md"
        sidecar_path = PENDING_DIR / f"{stem}.json"

        if md_filename in manifest["transcripts"] or (TRANSCRIPT_DIR / md_filename).exists():
            log.info("  Already in manifest, cleaning leftover audio: %s", stem)
            if not keep_audio and audio_path.exists():
                audio_path.unlink()
            if sidecar_path.exists():
                sidecar_path.unlink()
            continue

        try:
            metadata = json.loads(sidecar_path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            log.warning("  Cannot read sidecar for %s: %s (skipping)", stem, e)
            continue

        log.info("  Transcribing: %s", stem)
        transcript_text = transcribe_audio(audio_path)
        if not transcript_text:
            log.warning("    Skipping (empty or failed). Audio kept for retry.")
            continue

        content = build_markdown(stem, transcript_text, metadata)
        md_path = TRANSCRIPT_DIR / md_filename
        md_path.write_text(content, encoding="utf-8")

        word_count = len(transcript_text.split())
        manifest["transcripts"][md_filename] = {
            "title": metadata.get("title", stem),
            "source": metadata.get("source", "unknown"),
            "url": metadata.get("url", ""),
            "date": metadata.get("date", ""),
            "duration": metadata.get("duration", ""),
            "filename": md_filename,
            "audio_file": audio_path.name,
            "word_count": word_count,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }
        # Save incrementally so a crash mid-batch doesn't lose completed work
        save_manifest(manifest)

        if not keep_audio:
            audio_path.unlink()
        sidecar_path.unlink()

        transcribed += 1
        log.info("    Saved: %s (%d words)", md_filename, word_count)

    return transcribed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def download_new_episodes(
    days: int,
    max_episodes: int,
    feeds: list[str] | None,
) -> int:
    """Phase 1: download new episodes from RSS feeds into pending/."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    manifest.setdefault("transcripts", {})

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

            if transcript_filename in manifest.get("transcripts", {}):
                log.info("  Already processed: %s", title)
                continue

            audio_path = download_episode(feed_key, entry, pub_date)
            if audio_path:
                total_downloaded += 1
                episode_count += 1

    log.info("Downloaded %d new episode(s) to pending/.", total_downloaded)
    return total_downloaded


def run(
    days: int = 3,
    max_episodes: int = 5,
    feeds: list[str] | None = None,
    transcribe_only: bool = False,
    keep_audio: bool = False,
) -> None:
    """Full pipeline: download → transcribe → write markdown."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

    if not transcribe_only:
        download_new_episodes(days=days, max_episodes=max_episodes, feeds=feeds)

    # Anything in pending/ (new downloads + any backlog from prior failed runs)
    pending_audio = list(PENDING_DIR.glob("*.mp3"))
    if pending_audio:
        ensure_macwhisper_running()
        count = transcribe_pending(keep_audio=keep_audio)
        log.info("Done. Transcribed %d episode(s).", count)
    else:
        log.info("Done. No pending audio to transcribe.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and transcribe fantasy baseball podcasts via MacWhisper CLI"
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
        "--transcribe-only",
        action="store_true",
        help="Skip the RSS download phase; just drain pending/ through mw transcribe",
    )
    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="Don't delete audio files after successful transcription",
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
        print(f"\nPending folder:    {PENDING_DIR}")
        print(f"Transcripts folder: {TRANSCRIPT_DIR}")
        return

    run(
        days=args.days,
        max_episodes=args.max_episodes,
        feeds=args.feeds,
        transcribe_only=args.transcribe_only,
        keep_audio=args.keep_audio,
    )


if __name__ == "__main__":
    main()
