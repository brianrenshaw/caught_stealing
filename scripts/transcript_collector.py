#!/usr/bin/env python3
"""Collect MacWhisper transcripts and format them for analysis.

Runs in two modes:
  - One-shot: Collect any .txt files already in transcribed/ (default)
  - Watch mode (--watch): Continuously monitors transcribed/ and auto-collects
    the moment MacWhisper drops a .txt file that matches a pending .json sidecar

Each transcript gets wrapped in markdown with YAML frontmatter including the
episode release date (for recency-aware analysis), then moved to the final
transcripts/ folder. Source audio and sidecar files are cleaned up.

Usage:
    uv run python -m scripts.transcript_collector              # one-shot collect
    uv run python -m scripts.transcript_collector --watch      # watch mode (runs until stopped)
    uv run python -m scripts.transcript_collector --keep-audio # don't delete audio after collecting

Folder layout:
    data/content/audio/pending/       ← downloader puts .mp3 + .json here
    data/content/audio/pending/       ← MacWhisper outputs .txt here (next to source audio)
    data/content/transcripts/         ← this script writes final .md files here
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PENDING_DIR = PROJECT_ROOT / "data" / "content" / "audio" / "pending"
TRANSCRIPT_DIR = PROJECT_ROOT / "data" / "content" / "transcripts"
MANIFEST_PATH = PROJECT_ROOT / "data" / "content" / "manifest.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_manifest() -> dict:
    """Load or create the content manifest."""
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"blogs": {}, "transcripts": {}}


def save_manifest(manifest: dict) -> None:
    """Save the content manifest."""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=str))


def find_metadata(stem: str) -> tuple[dict | None, Path | None]:
    """Find the JSON metadata sidecar for a transcript.

    MacWhisper may name the output file slightly differently than our
    input stem. We try exact match first, then fuzzy match by checking
    if the transcript stem starts with a known sidecar stem.

    Returns (metadata_dict, sidecar_path) or (None, None).
    """
    exact = PENDING_DIR / f"{stem}.json"
    if exact.exists():
        return json.loads(exact.read_text()), exact

    for meta_file in PENDING_DIR.glob("*.json"):
        if stem.startswith(meta_file.stem) or meta_file.stem.startswith(stem):
            return json.loads(meta_file.read_text()), meta_file

    return None, None


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def collect_transcript(txt_path: Path, keep_audio: bool = False) -> dict | None:
    """Process a single MacWhisper .txt transcript.

    1. Read the transcript text
    2. Find the matching JSON metadata sidecar
    3. Write formatted markdown with YAML frontmatter
    4. Clean up audio + sidecar files
    5. Return metadata dict for the manifest
    """
    stem = txt_path.stem
    transcript_text = txt_path.read_text(encoding="utf-8").strip()

    if not transcript_text:
        log.warning("  Empty transcript: %s (skipping)", txt_path.name)
        return None

    metadata, sidecar_path = find_metadata(stem)

    if metadata:
        title = metadata.get("title", stem.replace("-", " ").title())
        source = metadata.get("source", "unknown")
        source_name = metadata.get("source_name", "Unknown Podcast")
        url = metadata.get("url", "")
        episode_date = metadata.get("date", "")
        duration = metadata.get("duration", "")
        description = metadata.get("description", "")
        audio_file = metadata.get("audio_file", f"{stem}.mp3")
    else:
        log.warning("  No metadata sidecar found for: %s (using filename)", stem)
        parts = stem.split("_", 2)
        date_str = parts[0] if len(parts) > 0 else ""
        source = parts[1] if len(parts) > 1 else "unknown"
        slug = parts[2] if len(parts) > 2 else stem
        title = slug.replace("-", " ").title()
        source_name = source.replace("_", " ").title()
        url = ""
        episode_date = f"{date_str}T00:00:00+00:00" if date_str else ""
        duration = ""
        description = ""
        audio_file = f"{stem}.mp3"

    word_count = len(transcript_text.split())
    md_filename = f"{stem}.md"

    frontmatter = f"""---
title: "{title.replace('"', '\\"')}"
source: {source}
source_name: {source_name}
url: {url}
date: {episode_date}
duration: "{duration}"
audio_file: {audio_file}
word_count: {word_count}
ingested_at: {datetime.now(timezone.utc).isoformat()}
---"""

    content = f"{frontmatter}\n\n# {title}\n\n"
    if description:
        content += f"## Episode Description\n\n{description}\n\n"
    content += f"## Transcript\n\n{transcript_text}\n"

    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = TRANSCRIPT_DIR / md_filename
    md_path.write_text(content, encoding="utf-8")
    log.info("  Saved: %s (%d words, episode date: %s)", md_filename, word_count, episode_date[:10])

    # Clean up
    txt_path.unlink()
    log.info("  Removed: %s", txt_path.name)

    if sidecar_path and sidecar_path.exists():
        sidecar_path.unlink()

    if not keep_audio:
        audio_path = PENDING_DIR / audio_file
        if audio_path.exists():
            audio_path.unlink()
            log.info("  Removed audio: %s", audio_file)

    return {
        "title": title,
        "source": source,
        "url": url,
        "date": episode_date,
        "duration": duration,
        "filename": md_filename,
        "audio_file": audio_file,
        "word_count": word_count,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


def process_txt_file(txt_path: Path, keep_audio: bool = False) -> None:
    """Process a single .txt file and update the manifest."""
    manifest = load_manifest()
    if "transcripts" not in manifest:
        manifest["transcripts"] = {}

    md_filename = f"{txt_path.stem}.md"
    if md_filename in manifest["transcripts"]:
        log.info("  Already collected: %s", md_filename)
        return

    result = collect_transcript(txt_path, keep_audio=keep_audio)
    if result:
        manifest["transcripts"][result["filename"]] = result
        save_manifest(manifest)


# ---------------------------------------------------------------------------
# Watch mode
# ---------------------------------------------------------------------------


def watch(keep_audio: bool = False) -> None:
    """Watch the pending/ folder and auto-collect .txt files as MacWhisper creates them."""
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    class TranscriptHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.suffix != ".txt":
                return

            # Wait briefly for MacWhisper to finish writing
            time.sleep(2)

            # Only process if there's a matching .json sidecar (it's one of ours)
            meta, _ = find_metadata(path.stem)
            if meta:
                log.info("New transcript detected: %s", path.name)
                process_txt_file(path, keep_audio=keep_audio)

        def on_moved(self, event):
            """Handle moves/renames — MacWhisper may write to a temp file first."""
            if event.is_directory:
                return
            dest = Path(event.dest_path)
            if dest.suffix != ".txt":
                return

            time.sleep(2)
            meta, _ = find_metadata(dest.stem)
            if meta:
                log.info("New transcript detected (moved): %s", dest.name)
                process_txt_file(dest, keep_audio=keep_audio)

    # First, collect anything already sitting there
    for txt_path in sorted(PENDING_DIR.glob("*.txt")):
        meta, _ = find_metadata(txt_path.stem)
        if meta:
            log.info("Found existing transcript: %s", txt_path.name)
            process_txt_file(txt_path, keep_audio=keep_audio)

    observer = Observer()
    observer.schedule(TranscriptHandler(), str(PENDING_DIR), recursive=False)
    observer.start()
    log.info("Watching %s for new transcripts... (Ctrl+C to stop)", PENDING_DIR)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        log.info("Stopped watching.")
    observer.join()


# ---------------------------------------------------------------------------
# One-shot mode
# ---------------------------------------------------------------------------


def run(keep_audio: bool = False) -> None:
    """Collect all pending MacWhisper transcripts (one-shot)."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()

    if "transcripts" not in manifest:
        manifest["transcripts"] = {}

    # Find .txt files in pending/ that have a matching .json sidecar
    txt_files = sorted(
        f for f in PENDING_DIR.glob("*.txt") if find_metadata(f.stem)[0] is not None
    )

    if not txt_files:
        log.info("No new transcripts found in %s", PENDING_DIR)
        return

    log.info("Found %d transcript(s) to collect", len(txt_files))
    collected = 0

    for txt_path in txt_files:
        md_filename = f"{txt_path.stem}.md"
        if md_filename in manifest["transcripts"]:
            log.info("  Already collected: %s", md_filename)
            continue

        result = collect_transcript(txt_path, keep_audio=keep_audio)
        if result:
            manifest["transcripts"][result["filename"]] = result
            collected += 1

    save_manifest(manifest)
    log.info("Done. Collected %d new transcript(s).", collected)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect MacWhisper transcripts and format for analysis"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch mode: continuously monitor for new transcripts",
    )
    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="Don't delete audio files after collecting transcripts",
    )
    args = parser.parse_args()

    if args.watch:
        watch(keep_audio=args.keep_audio)
    else:
        run(keep_audio=args.keep_audio)


if __name__ == "__main__":
    main()
