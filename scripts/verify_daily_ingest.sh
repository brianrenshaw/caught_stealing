#!/bin/bash
# Verify the most recent daily content ingest succeeded.
# Runs after the 3 AM ingest. Zero API spend — just inspects artifacts.
# Exits 0 on pass, 1 on fail. On fail: macOS notification + appends to verify_problems.log.

set -u

PROJECT_DIR="/Users/brianrenshaw/Projects/fantasy_baseball_br"
LOG_DIR="$PROJECT_DIR/data/content/logs"
ANALYSIS_DIR="$PROJECT_DIR/data/content/analysis"
DB_PATH="$PROJECT_DIR/fantasy_baseball.db"
TODAY=$(date +%Y-%m-%d)
INGEST_LOG="$LOG_DIR/ingest_${TODAY}.log"
PROBLEMS_LOG="$LOG_DIR/verify_problems.log"
STATUS_FILE="$LOG_DIR/last_verified.txt"

problems=()

check() {
    local name="$1" ok="$2" detail="$3"
    if [ "$ok" = "1" ]; then
        echo "  PASS  $name"
    else
        echo "  FAIL  $name — $detail"
        problems+=("$name: $detail")
    fi
}

echo "=== verify_daily_ingest $TODAY $(date +%H:%M:%S) ==="

if [ -f "$INGEST_LOG" ]; then
    check "ingest log exists" 1 ""
    grep -q "Content ingest finished:" "$INGEST_LOG" && f=1 || f=0
    check "ingest reached final marker" "$f" "no 'Content ingest finished:' line in $INGEST_LOG"

    grep -q "PIPELINE COMPLETE.*'status': 'success'" "$INGEST_LOG" && f=1 || f=0
    check "Yahoo ETL succeeded" "$f" "no 'PIPELINE COMPLETE status: success' line"

    UPLOADED_LINE=$(grep "^Uploaded [0-9]* report" "$INGEST_LOG" | tail -1)
    UPLOADED_N=$(echo "$UPLOADED_LINE" | grep -oE "[0-9]+" | head -1)
    if [ -n "$UPLOADED_N" ] && [ "$UPLOADED_N" -gt 0 ]; then
        check "Fly upload count" 1 ""
    else
        check "Fly upload count" 0 "Uploaded line missing or 0 (got: '$UPLOADED_LINE')"
    fi
else
    check "ingest log exists" 0 "missing $INGEST_LOG"
fi

ANALYSIS_COUNT=$(find "$ANALYSIS_DIR" -maxdepth 1 -name "${TODAY}_*.md" 2>/dev/null | wc -l | tr -d ' ')
if [ "$ANALYSIS_COUNT" -gt 0 ]; then
    check "analysis markdowns for today (n=$ANALYSIS_COUNT)" 1 ""
else
    check "analysis markdowns for today" 0 "no ${TODAY}_*.md files in $ANALYSIS_DIR"
fi

if [ -f "$DB_PATH" ]; then
    DB_AGE_HOURS=$(( ( $(date +%s) - $(stat -f %m "$DB_PATH") ) / 3600 ))
    if [ "$DB_AGE_HOURS" -lt 6 ]; then
        check "DB recently updated (${DB_AGE_HOURS}h ago)" 1 ""
    else
        check "DB recently updated" 0 "fantasy_baseball.db last modified ${DB_AGE_HOURS}h ago"
    fi
else
    check "DB exists" 0 "missing $DB_PATH"
fi

# Soft check: Cardinals daily report. WARN-only — failure here doesn't fail the verifier
# because the fantasy report is the primary deliverable; Cardinals is desirable but
# not blocking.
CARDINALS_MD="$ANALYSIS_DIR/${TODAY}_cardinals-daily.md"
if [ -f "$CARDINALS_MD" ]; then
    echo "  PASS  Cardinals daily report present"
else
    echo "  WARN  Cardinals daily report missing ($CARDINALS_MD) — soft check, not failing"
fi

# Hard check: a quarantined fact-check-failed report. If the runner generated a
# Cardinals report and the fact-checker rejected it twice, the MD is in
# factcheck_failed/. Escalate immediately — bad numbers are the kind of bug
# that lands on Blot if we don't notice.
FACTCHECK_FAILED_MD="$ANALYSIS_DIR/factcheck_failed/${TODAY}_cardinals-daily.md"
FACTCHECK_FAILED_LOG="$ANALYSIS_DIR/factcheck_failed/${TODAY}_cardinals-daily.factcheck.json"
if [ -f "$FACTCHECK_FAILED_MD" ]; then
    ISSUE_COUNT=$(grep -c '"claim":' "$FACTCHECK_FAILED_LOG" 2>/dev/null || echo "?")
    check "Cardinals fact-check passed" 0 "report quarantined with $ISSUE_COUNT unsupported claims — see $FACTCHECK_FAILED_LOG"
else
    echo "  PASS  Cardinals fact-check (no quarantined report)"
fi

# Soft check: Cardinals post landed in the Blot Dropbox folder. Catches the case
# where the report generated locally but the Blot publisher silently skipped
# (e.g., Dropbox app paused, folder unmounted, transient write error). FAIL-level
# this one because publishing to the blog is the user-facing deliverable.
BLOT_POST="$HOME/Library/CloudStorage/Dropbox-Brianrenshawmedia/Brian Renshaw/Apps/Blot/Posts/${TODAY}-cardinals-daily.md"
if [ -f "$BLOT_POST" ]; then
    check "Blot post published" 1 ""
elif [ ! -f "$CARDINALS_MD" ]; then
    # Local report missing too — already flagged above, don't double-count.
    echo "  SKIP  Blot post check (local Cardinals MD missing — see prior warning)"
else
    check "Blot post published" 0 "local Cardinals MD exists but Blot post is missing at $BLOT_POST — run scripts/republish_to_blot.sh to retry"
fi

echo ""
if [ ${#problems[@]} -eq 0 ]; then
    echo "ALL CHECKS PASSED"
    echo "$TODAY $(date +%H:%M:%S) PASS" > "$STATUS_FILE"
    exit 0
fi

echo "FAILED CHECKS: ${#problems[@]}"
{
    echo "=== $TODAY $(date +%H:%M:%S) FAIL ==="
    for p in "${problems[@]}"; do echo "  - $p"; done
    echo ""
} >> "$PROBLEMS_LOG"

NOTIF_BODY=$(printf '%s\n' "${problems[@]}" | head -3)
osascript -e "display notification \"${NOTIF_BODY//\"/\\\"}\" with title \"Fantasy Baseball ingest FAILED\" subtitle \"$TODAY — see verify_problems.log\"" 2>/dev/null || true

echo "$TODAY $(date +%H:%M:%S) FAIL (${#problems[@]} problems)" > "$STATUS_FILE"
exit 1
