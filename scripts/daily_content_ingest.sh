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

# Step 3.5: Refresh Yahoo league data (standings, rosters) before analysis
echo ""
echo "--- Yahoo League Sync ---"
uv run python -m app.etl.pipeline || {
    echo "WARNING: Yahoo league sync failed — analysis may use stale data"
}

# Step 4: Generate daily analysis reports from ingested content
echo ""
echo "--- Daily Analysis ---"
uv run python -m scripts.daily_analysis || {
    echo "WARNING: Daily analysis generation failed"
}

ANALYSIS_DIR="$PROJECT_DIR/data/content/analysis"
TODAY=$(date +%Y-%m-%d)

# Step 4.4: Generate Cardinals-only daily report (parallel to fantasy report).
# Pulls Cardinals-specific blogs/podcasts + yesterday's MLB postgame Statcast data.
echo ""
echo "--- Cardinals Daily Report ---"
uv run python -m scripts.cardinals_daily_report || {
    echo "WARNING: Cardinals daily report generation failed"
}

# Step 4.45: League-wide MLB roundup. Ships to Blot only (Posts/MLB/ subfolder).
# Non-fatal — a Savant outage here shouldn't kill the rest of the pipeline.
echo ""
echo "--- MLB Daily Roundup ---"
uv run python -m scripts.mlb_daily_roundup || {
    echo "WARNING: MLB daily roundup generation failed"
}

# Step 4.5: Render the fantasy report to a Cardinals-themed PDF.
# Only the fantasy report flows through PDF + Readdle + Fly; the Cardinals
# digest ships to Blot only (the python script publishes inside Step 4.4).
echo ""
echo "--- PDF Export (Cardinals theme) ---"
MD2PDF="$HOME/Projects/md2pdf/md2pdf.mjs"
RENDERED_PDFS=()

# Fantasy report (only one of weekly-intel / daily-intel exists per day).
FANTASY_MD=""
for candidate in "$ANALYSIS_DIR/${TODAY}_weekly-intel.md" "$ANALYSIS_DIR/${TODAY}_daily-intel.md"; do
    if [ -f "$candidate" ]; then
        FANTASY_MD="$candidate"
        break
    fi
done

if [ ! -x "$(command -v node)" ] || [ ! -f "$MD2PDF" ]; then
    echo "WARNING: skipped PDF export (node or $MD2PDF missing)"
elif [ -z "$FANTASY_MD" ]; then
    echo "WARNING: no compiled fantasy markdown found for $TODAY"
else
    if node "$MD2PDF" cardinals "$FANTASY_MD" >/dev/null 2>&1; then
        pdf="${FANTASY_MD%.md}.pdf"
        echo "Rendered: $(basename "$pdf")"
        RENDERED_PDFS+=("$pdf")
    else
        echo "WARNING: PDF render failed for $(basename "$FANTASY_MD")"
    fi
fi

# Step 4.6: Copy each rendered PDF into the Readdle iCloud sync folder for mobile.
echo ""
echo "--- Sync compiled PDFs to Readdle iCloud folder ---"
READDLE_DIR="$HOME/Library/Mobile Documents/3L68KQB4HG~com~readdle~CommonDocuments/Documents/Fantasy Baseball Analysis"
if [ ! -d "$READDLE_DIR" ]; then
    echo "WARNING: Readdle sync folder not found at $READDLE_DIR"
elif [ ${#RENDERED_PDFS[@]} -eq 0 ]; then
    echo "WARNING: no PDFs to sync"
else
    SYNCED=0
    for pdf in "${RENDERED_PDFS[@]}"; do
        if cp "$pdf" "$READDLE_DIR/"; then
            echo "Copied: $(basename "$pdf") to Readdle"
            SYNCED=$((SYNCED + 1))
        else
            echo "WARNING: copy to Readdle failed for $(basename "$pdf")"
        fi
    done
    echo "Synced $SYNCED PDF(s) to Readdle"
fi

# Step 5: Upload fantasy markdown reports to Fly.io volume (markdown only —
# web app renders MD). The Cardinals digest is intentionally excluded — that
# report ships to Blot only, not the Fly-hosted fantasy web app.
echo ""
echo "--- Syncing Fantasy Markdown Reports to Fly.io ---"
UPLOADED=0
for f in "$ANALYSIS_DIR/${TODAY}"_*.md; do
    [ -f "$f" ] || continue
    BASENAME=$(basename "$f")
    # Skip Blot-only reports (Cardinals digest, MLB roundup) — ship to Blot, not Fly.
    case "$BASENAME" in
        *cardinals-daily*) continue ;;
        *mlb-roundup*) continue ;;
    esac
    # `sftp put` silently SKIPS when the destination exists (e.g., a regen
    # within the same day). Delete first so the upload always reflects local.
    flyctl ssh console --app fantasy-baseball-br -C "rm -f /data/content/analysis/$BASENAME" >/dev/null 2>&1
    flyctl ssh sftp shell --app fantasy-baseball-br <<EOF
put $f /data/content/analysis/$BASENAME
EOF
    if [ $? -eq 0 ]; then
        echo "  Uploaded: $BASENAME"
        UPLOADED=$((UPLOADED + 1))
    else
        echo "  WARNING: Failed to upload $BASENAME"
    fi
done
echo "Uploaded $UPLOADED fantasy report(s) to Fly.io"

echo ""
echo "=========================================="
echo "Content ingest finished: $(date)"
echo "=========================================="
