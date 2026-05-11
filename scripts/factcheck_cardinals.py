"""Fact-check the Score and Data section of a Cardinals daily report.

Reads a generated Cardinals MD and the POSTGAME DATA JSON it was built from,
extracts the **Score and Data** section, and asks Claude (via `claude -p`, no
API spend) to identify every numeric or factual claim in the prose that is
NOT supported by the JSON.

Used by `scripts/cardinals_daily_report.py` between generation and publish —
on failure, the daily script regenerates once with the issues fed back, then
blocks all downstream destinations if the retry still fails.

Standalone CLI:
    uv run python -m scripts.factcheck_cardinals \\
        data/content/analysis/2026-05-11_cardinals-daily.md
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from scripts.daily_analysis import _invoke_claude_cli

log = logging.getLogger(__name__)

FACTCHECK_MODEL = "claude-sonnet-4-6"

FACTCHECK_SYSTEM_PROMPT = """You are a strict fact-checker for a baseball beat-writer's game story. The story was written by another model from a JSON payload of MLB Stats API boxscore data + Baseball Savant gamefeed data. Your only job: identify every numeric or factual claim in the prose that is NOT supported by the JSON.

CLAIMS THAT MUST BE VERIFIED AGAINST THE JSON:
- Pitch velocities ("98.5 mph Sinker", "76.3 mph Knuckle Curve") → must match a `pitch_velo_mph`, `start_speed`, or `velo_mph` value
- Exit velocities ("105.2 mph EV", "108.3 mph off the bat") → must match a `launch_speed` / `ev_mph` value
- Hit distances ("425 ft", "212-foot") → must match a `hit_distance_ft` / `max_hit_distance_ft` value
- xBA / xwOBA (".980 xBA", ".010 xBA") → must match an `xba` / `best_xba` value
- Spin rates ("2,317 rpm") → must match a `spin_rate` / `spin_rpm` value
- Launch angles ("31-degree", "31° LA") → must match a `launch_angle` / `la_deg` value
- WPA / win-probability percentages ("+48.5%", "29.5% WPA") → must match `wpa_delta_pct` / `wpa_pct` / `home_wp_after_pct`
- Inning-specific final scores, run totals, hit totals → must match `line_score.totals` or `scoring_plays`
- Pitching lines ("5.0 IP, 0 ER, 5 K, 4 BB") → must match `top_performers[].pitching_line` or `boxscore.pitchers`
- Player names attached to events → must match a name appearing in `scoring_plays`, `wpa.key_swings`, `top_performers`, `boxscore`, or `statcast_highlights`

CLAIMS THAT MUST BE FLAGGED AS FABRICATION (cannot be in JSON):
- Player ages, "decade's age gap", multi-game streaks, season-long counting stats not in the data block
- Forward-looking content: upcoming opponent, travel day, next probable pitcher, scheduled game time ("Tuesday at 8:40 p.m.", "next series at Sacramento", "Andre Pallante listed for the start")
- Cross-game references ("Saturday's 4-2 defeat", "second straight one-run loss") unless POSTGAME DATA explicitly contains the prior result
- Direct citations to blogs/podcasts in this section ("per Locked On Cardinals", "Viva El Birdos reported") — Score and Data must run on JSON only

CLAIMS THAT DO NOT NEED VERIFICATION:
- Contextual phrasing derivable from inning + outs + scoring_plays ("two outs", "with the tying runner stranded", "in the bottom of the ninth", "loaded the bases")
- Beat-writer color and metaphor ("low-oxygen baseball", "vintage triple-digit", "the gamefeed recorded")
- Pitch sequencing inferred from per-pitch streams ("the third 98.5 mph Sinker of the at-bat") — only flag if directly contradicted
- Verbatim play descriptions from `scoring_plays[].description` or `wpa.key_swings[].description`

For each suspect claim, locate the supporting value if one exists nearby (the prose may have rounded). Include the actual JSON value so the regenerator can correct it.

Output STRICT JSON only (no prose around it):
{
  "verdict": "pass" | "fail",
  "issue_count": <int>,
  "issues": [
    {
      "claim": "<exact phrase from the prose>",
      "category": "velocity|ev|distance|xba|spin|la|wpa|score|pitching_line|season-total|forward-looking|source-citation|name|other",
      "why_suspect": "<why this claim cannot be verified against the JSON>",
      "json_value_if_close": "<actual JSON value if the claim is close to a real one, else null>"
    }
  ]
}

Verdict is "pass" ONLY if issue_count == 0. Any unsupported claim → "fail".
"""


@dataclass
class FactCheckIssue:
    claim: str
    category: str
    why_suspect: str
    json_value_if_close: str | None = None

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "category": self.category,
            "why_suspect": self.why_suspect,
            "json_value_if_close": self.json_value_if_close,
        }


@dataclass
class FactCheckResult:
    verdict: str  # "pass" or "fail"
    issues: list[FactCheckIssue] = field(default_factory=list)
    raw_response: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == "pass" and not self.issues

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "issue_count": len(self.issues),
            "issues": [i.to_dict() for i in self.issues],
        }

    def issue_summary(self) -> str:
        if not self.issues:
            return "(no issues)"
        return "\n".join(
            f"- [{i.category}] \"{i.claim}\" — {i.why_suspect}"
            + (f" (data: {i.json_value_if_close})" if i.json_value_if_close else "")
            for i in self.issues
        )


SCORE_AND_DATA_RE = re.compile(
    r"^##\s+Score and Data.*?(?=^##\s+\S)",
    re.MULTILINE | re.DOTALL,
)


def extract_score_and_data(md_text: str) -> str | None:
    """Pull the Score and Data section from a Cardinals daily MD.

    Returns the section text up to (but not including) the next H2 heading.
    Returns None if no Score and Data section is found.
    """
    m = SCORE_AND_DATA_RE.search(md_text)
    if not m:
        return None
    return m.group(0).rstrip()


def _parse_factcheck_response(raw: str) -> FactCheckResult:
    """Parse the strict JSON the fact-checker is supposed to return.

    Defensive: if the response wraps the JSON in prose/fences, extract the
    first balanced JSON object.
    """
    if not raw:
        return FactCheckResult(
            verdict="fail",
            issues=[FactCheckIssue(
                claim="(no response)", category="other",
                why_suspect="Fact-checker returned empty output",
            )],
            raw_response=raw,
        )

    cleaned = raw.strip()
    # Strip ```json ... ``` fences if present
    fence = re.match(r"^```(?:json)?\s*(\{.*?\})\s*```\s*$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    else:
        # Find first { ... last } window
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            cleaned = cleaned[start:end + 1]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.warning("Fact-checker JSON parse failed: %s — treating as fail", e)
        return FactCheckResult(
            verdict="fail",
            issues=[FactCheckIssue(
                claim="(unparseable response)", category="other",
                why_suspect=f"Fact-checker output was not valid JSON: {e}",
            )],
            raw_response=raw,
        )

    verdict = (data.get("verdict") or "fail").strip().lower()
    issues_data = data.get("issues") or []
    issues = [
        FactCheckIssue(
            claim=str(i.get("claim", "")),
            category=str(i.get("category", "other")),
            why_suspect=str(i.get("why_suspect", "")),
            json_value_if_close=(
                str(i["json_value_if_close"])
                if i.get("json_value_if_close") not in (None, "", "null")
                else None
            ),
        )
        for i in issues_data
        if isinstance(i, dict) and i.get("claim")
    ]
    # Coerce verdict consistency: if any issues, force fail.
    if issues and verdict == "pass":
        verdict = "fail"
    return FactCheckResult(verdict=verdict, issues=issues, raw_response=raw)


def factcheck_score_and_data(
    score_section: str, postgame: dict | None
) -> FactCheckResult:
    """Run the Claude-based fact-checker against the Score and Data section.

    `postgame` may be None for off-day reports — in that case the fact-checker
    will look for the explicit "(no game)" pivot and flag anything else.
    """
    if not score_section:
        return FactCheckResult(
            verdict="fail",
            issues=[FactCheckIssue(
                claim="(no Score and Data section)", category="other",
                why_suspect="Could not locate the section in the generated MD",
            )],
        )

    postgame_json = (
        json.dumps(postgame, indent=2, default=str) if postgame is not None
        else "null  // no game on the target date (off day or postponement)"
    )

    user_message = (
        "Fact-check the following Score and Data section against the POSTGAME DATA "
        "JSON it was generated from. Output STRICT JSON per the system prompt — no "
        "prose, no markdown fences.\n\n"
        "---\n\n"
        "# POSTGAME DATA\n\n"
        f"```json\n{postgame_json}\n```\n\n"
        "---\n\n"
        "# SCORE AND DATA SECTION TO VERIFY\n\n"
        f"{score_section}\n"
    )

    log.info("Running fact-check on Score and Data section (%d chars)…", len(score_section))
    try:
        text, _in_toks, _out_toks, _stop = _invoke_claude_cli(
            FACTCHECK_MODEL, FACTCHECK_SYSTEM_PROMPT, user_message
        )
    except Exception as e:
        log.error("Fact-check invocation failed: %s", e)
        return FactCheckResult(
            verdict="fail",
            issues=[FactCheckIssue(
                claim="(fact-check call failed)", category="other",
                why_suspect=f"claude -p invocation raised: {e}",
            )],
        )

    result = _parse_factcheck_response(text or "")
    log.info("Fact-check verdict: %s (%d issues)", result.verdict, len(result.issues))
    return result


# ---------------------------------------------------------------------------
# Standalone CLI for ad-hoc verification of an already-written report
# ---------------------------------------------------------------------------


def _load_postgame_for_md(md_path: Path) -> dict | None:
    """Re-fetch the postgame payload for the game referenced by an MD file.

    The MD's frontmatter has the report's `date`; the game is yesterday relative
    to that. Re-fetching is cheap (Savant gamefeed responds in ~1s).
    """
    from app.services.cardinals_postgame import get_cardinals_postgame

    text = md_path.read_text(encoding="utf-8")
    m = re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", text, re.MULTILINE)
    if not m:
        log.warning("Could not extract report date from frontmatter — using today")
        report_date = date.today()
    else:
        report_date = date.fromisoformat(m.group(1))
    return get_cardinals_postgame(report_date - timedelta(days=1))


def main() -> int:
    parser = argparse.ArgumentParser(description="Fact-check a Cardinals daily MD")
    parser.add_argument("md_path", type=Path, help="Path to {date}_cardinals-daily.md")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    if not args.json:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )

    if not args.md_path.exists():
        print(f"ERROR: {args.md_path} does not exist", file=sys.stderr)
        return 2

    md_text = args.md_path.read_text(encoding="utf-8")
    section = extract_score_and_data(md_text)
    if not section:
        print(f"ERROR: no Score and Data section found in {args.md_path}", file=sys.stderr)
        return 2

    postgame = _load_postgame_for_md(args.md_path)
    result = factcheck_score_and_data(section, postgame)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"Verdict: {result.verdict.upper()}")
        print(f"Issues:  {len(result.issues)}")
        if result.issues:
            print()
            print(result.issue_summary())
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
