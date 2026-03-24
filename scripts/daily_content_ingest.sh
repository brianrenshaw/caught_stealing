#!/bin/bash
# Daily content ingestion for fantasy baseball analysis.
# 1. Fetches blog articles from RSS feeds
# 2. Downloads podcast episodes into MacWhisper's watch folder
# 3. Collects any completed MacWhisper transcripts from previous runs
# Designed to be run by launchd at 3 AM.

set -euo pipefail

PROJECT_DIR="/Users/brianrenshaw/Projects/fantasy_baseball_br"
LOG_DIR="$PROJECT_DIR/data/content/logs"
LOG_FILE="$LOG_DIR/ingest_$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================="
echo "Content ingest started: $(date)"
echo "=========================================="

cd "$PROJECT_DIR"

# Step 1: Collect any transcripts MacWhisper finished since last run
echo ""
echo "--- Collecting MacWhisper Transcripts ---"
uv run python -m scripts.transcript_collector || {
    echo "WARNING: Transcript collector failed"
}

# Step 2: Fetch blog articles (last 2 days to catch anything missed)
echo ""
echo "--- Blog Ingest ---"
uv run python -m scripts.blog_ingest --days 2 --max-articles 10 || {
    echo "WARNING: Blog ingest failed"
}

# Step 3: Download new podcast episodes (opens MacWhisper if needed)
echo ""
echo "--- Podcast Download ---"
uv run python -m scripts.podcast_transcriber --days 2 --max-episodes 5 || {
    echo "WARNING: Podcast downloader failed"
}

# Step 4: Generate daily analysis reports from ingested content
echo ""
echo "--- Daily Analysis ---"
uv run python -m scripts.daily_analysis || {
    echo "WARNING: Daily analysis generation failed"
}

echo ""
echo "=========================================="
echo "Content ingest finished: $(date)"
echo "=========================================="
