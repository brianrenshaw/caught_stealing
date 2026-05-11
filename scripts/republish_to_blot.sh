#!/bin/bash
# Re-publish today's (or a specific date's) Cardinals report to Blot
# WITHOUT regenerating it through Claude. Useful when:
#   - The 3 AM run published locally but Blot publish silently skipped
#     (Dropbox app was paused, folder unmounted, etc.)
#   - The 4 AM verifier flagged "Blot post published" FAIL
#   - You manually edited the local cardinals-daily.md and want to re-push
#
# Usage:
#   ./scripts/republish_to_blot.sh              # today
#   ./scripts/republish_to_blot.sh 2026-05-10   # specific date

set -euo pipefail

PROJECT_DIR="/Users/brianrenshaw/Projects/fantasy_baseball_br"
TARGET_DATE="${1:-$(date +%Y-%m-%d)}"
# Use the install location so this works under launchd / cron where ~/.local/bin
# isn't on PATH.
UV="${UV_BIN:-/Users/brianrenshaw/.local/bin/uv}"

cd "$PROJECT_DIR"

"$UV" run python - <<PYEOF
from datetime import date, timedelta
from pathlib import Path
import re

from scripts.cardinals_daily_report import _publish_to_blot, load_player_links, ANALYSIS_DIR
from app.services.cardinals_postgame import get_cardinals_postgame

today = date.fromisoformat("${TARGET_DATE}")
md_path = ANALYSIS_DIR / f"{today.isoformat()}_cardinals-daily.md"

if not md_path.exists():
    raise SystemExit(f"Local Cardinals MD not found: {md_path}")

raw = md_path.read_text(encoding="utf-8")
# Strip our YAML frontmatter so _publish_to_blot sees just the body.
body = re.sub(r"^---\n.+?\n---\n+", "", raw, count=1, flags=re.S)

# Re-derive postgame data for the same game (yesterday relative to today).
postgame = get_cardinals_postgame(today - timedelta(days=1))

links = load_player_links()
out = _publish_to_blot(today, body, links, postgame=postgame)
if out:
    print(f"OK: republished {out}")
else:
    raise SystemExit("Publish skipped — Blot Posts folder unavailable (is Dropbox running?)")
PYEOF
