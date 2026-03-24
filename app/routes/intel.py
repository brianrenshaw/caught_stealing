"""Intel tab — daily analysis reports from expert content + league data."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ANALYSIS_DIR = Path("data/content/analysis")

logger = logging.getLogger(__name__)

# Report type display labels
TYPE_LABELS = {
    "daily-intel": "Daily Briefing",
    "weekly-intel": "Weekly Intel (Full)",
    "last-week-recap": "Last Week's Recap",
    "roster-intel": "My Roster Intel",
    "matchup-preview": "Matchup Preview",
    "waiver-intel": "Waiver Targets",
    "trade-intel": "Trade Signals",
    "projection-watch": "Projection Watch",
    "around-the-league": "Around the League",
    "cardinals-corner": "Cardinals Corner",
    "sibling-rivalry": "Sibling Rivalry",
    "injury-watch": "Injury Watch",
    "action-items": "Action Items",
    "projection-accuracy": "Projection Accuracy",
    "league-accuracy": "League Accuracy",
    # Legacy
    "daily-briefing": "Daily Briefing",
    "key-takeaways": "Key Takeaways",
    "lineup-notes": "Weekly Lineup Notes",
}


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text."""
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            val = val.strip().strip('"').strip("'")
            meta[key.strip()] = val

    return meta, parts[2].strip()


def load_reports() -> list[dict]:
    """Scan analysis directory for report files.

    Returns list of dicts with: filename, title, type, type_label, date, source_count
    sorted by date descending.
    """
    if not ANALYSIS_DIR.exists():
        return []

    reports = []
    for filepath in ANALYSIS_DIR.glob("*.md"):
        try:
            text = filepath.read_text(encoding="utf-8")
            meta, _ = parse_frontmatter(text)

            report_type = meta.get("type", "note")
            date_str = meta.get("date", "")

            try:
                report_date = date.fromisoformat(date_str) if date_str else None
            except ValueError:
                report_date = None

            reports.append({
                "filename": filepath.name,
                "title": meta.get("title", filepath.stem.replace("-", " ").title()),
                "type": report_type,
                "type_label": TYPE_LABELS.get(report_type, "Notes"),
                "date": report_date,
                "date_display": report_date.strftime("%b %d, %Y") if report_date else "Unknown",
                "source_count": meta.get("source_count", ""),
                "input_tokens": meta.get("input_tokens", ""),
                "output_tokens": meta.get("output_tokens", ""),
            })
        except Exception as e:
            logger.warning("Failed to parse %s: %s", filepath.name, e)

    reports.sort(key=lambda r: r["date"] or date.min, reverse=True)
    return reports


def group_reports_by_date(reports: list[dict]) -> list[tuple[str, list[dict]]]:
    """Group reports by date for display."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in reports:
        key = r["date_display"]
        grouped[key].append(r)

    # Maintain order (already sorted by date desc)
    seen = []
    result = []
    for r in reports:
        key = r["date_display"]
        if key not in seen:
            seen.append(key)
            result.append((key, grouped[key]))
    return result


@router.get("/intel")
async def intel_page(request: Request):
    """Main Intel page — lists all analysis reports."""
    reports = load_reports()
    grouped = group_reports_by_date(reports)

    # Find the most recent briefing for auto-load
    latest_briefing = next(
        (r for r in reports if r["type"] in ("daily-intel", "weekly-intel")), None
    )

    return templates.TemplateResponse(
        request,
        "intel.html",
        {
            "grouped_reports": grouped,
            "latest_briefing": latest_briefing,
            "report_count": len(reports),
        },
    )


@router.get("/intel/report")
async def intel_report(request: Request, file: str = ""):
    """Load a single report as an HTMX partial."""
    # Sanitize filename
    if not file or not re.match(r"^[\w\-\.]+\.md$", file):
        return templates.TemplateResponse(
            request,
            "partials/intel_report.html",
            {"report_title": "Error", "report_content": "Invalid file.", "report_meta": {}},
        )

    filepath = ANALYSIS_DIR / file
    if not filepath.exists() or not filepath.is_relative_to(ANALYSIS_DIR):
        return templates.TemplateResponse(
            request,
            "partials/intel_report.html",
            {"report_title": "Not Found", "report_content": "Report not found.", "report_meta": {}},
        )

    text = filepath.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)

    return templates.TemplateResponse(
        request,
        "partials/intel_report.html",
        {
            "report_title": meta.get("title", file),
            "report_content": body,
            "report_meta": meta,
        },
    )


@router.post("/intel/refresh")
async def intel_refresh(request: Request):
    """Regenerate the daily briefing on demand."""
    import asyncio

    try:
        # Run the analysis script
        proc = await asyncio.create_subprocess_exec(
            "uv", "run", "python", "-m", "scripts.daily_analysis",
            "--mode", "daily", "--force",
            cwd=str(Path.cwd()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error("Analysis refresh failed: %s", stderr.decode()[:500])

        # Return the latest briefing
        reports = load_reports()
        latest = next(
            (r for r in reports if r["type"] in ("daily-intel", "weekly-intel")), None
        )

        if latest:
            filepath = ANALYSIS_DIR / latest["filename"]
            text = filepath.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(text)

            return templates.TemplateResponse(
                request,
                "partials/intel_report.html",
                {
                    "report_title": meta.get("title", "Daily Briefing"),
                    "report_content": body,
                    "report_meta": meta,
                    "refresh_success": True,
                    "reports_generated": len([r for r in reports if r["date"] == date.today()]),
                },
            )

    except Exception as e:
        logger.error("Analysis refresh error: %s", e)

    return templates.TemplateResponse(
        request,
        "partials/intel_report.html",
        {
            "report_title": "Refresh Failed",
            "report_content": "Analysis generation failed. Check logs for details.",
            "report_meta": {},
        },
    )
