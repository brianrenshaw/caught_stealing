"""Fact-check per-game summaries in an MLB daily roundup post.

Mirror of `scripts/factcheck_cardinals.py` but scoped to the league-wide
roundup: each of the day's 15ish games gets a 3-4 sentence summary, and
this module verifies every numeric / factual claim against the per-game
JSON payload it was generated from.

Used by `scripts/mlb_daily_roundup.py` between Claude's generation step and
publish — on failure, the runner regenerates once with the issues fed back,
then quarantines the report if the retry still fails.

Runs Opus 4.8 via the bundled Claude Code CLI (no metered API spend).
Standalone CLI:
    uv run python -m scripts.factcheck_mlb_roundup \\
        data/content/analysis/2026-05-11_mlb-roundup.md
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from scripts.daily_analysis import _invoke_claude_cli

log = logging.getLogger(__name__)

# Opus 4.8 by user preference — this runs at 3 AM, accuracy beats speed/cost.
FACTCHECK_MODEL = "claude-opus-4-8"

FACTCHECK_SYSTEM_PROMPT = """You are a strict fact-checker for MLB daily roundup prose. For every game in the supplied array you receive:
- a `summary` (the 3-4 sentence prose another model wrote)
- a `json` payload (the structured data that summary was generated from)

The `json` payload combines TWO independent ground-truth sources:
- Primary: Baseball Savant gamefeed data (`key_swings`, `scoring_plays`, `top_performers`, `team_records`, `hardest_hit`, `top_pitches`, plus derived `rbi` and `season_total` per play)
- Secondary: Baseball Reference cross-reference (`bbref.play_by_play` — every plate appearance with `inning`, `batter`, `pitcher`, `play_desc`, signed `wpa_pct`, `runs_outs`; plus `bbref.game_scores` per pitcher)

A claim is supported when EITHER source confirms it. A claim is FLAGGED when (a) it contradicts BOTH sources, (b) it contradicts one and the other is silent, or (c) neither source supports it. Use bbref's PBP especially to catch RBI-count errors, scoring-play misreads, and chronology mistakes (the `inning` field on each PBP row is the authoritative ordering).

Verify each game's summary against ONLY its own JSON — do not cross-reference between games.

CLAIMS THAT MUST BE VERIFIED AGAINST THE JSON:
- Final scores → must match `away_score` / `home_score` / `line_score.totals`
- Pitch velocities ("98.5 mph sinker", "76.3 mph curveball") → must match `pitch_velo_mph` / `velo_mph` / `start_speed` in `key_swings`, `top_pitches`, or `scoring_plays`
- Exit velocities ("105.2 mph EV", "108.3 mph drive") → must match `ev_mph` in `key_swings`, `hardest_hit`, or `scoring_plays`
- WPA percentages ("+24.1%", "swung win probability 23.1%", "worth 48.5 WPA points") → must match `wpa_delta_pct` (positive = home team gained, negative = home team lost) in `key_swings`, OR be derivable arithmetically from `home_wp_after_pct` and `wpa_delta_pct` within 0.5 percentage points. DERIVED VALUES ARE ACCEPTABLE: pre-play home WP = `home_wp_after_pct - wpa_delta_pct` (e.g. for a play with home_wp_after_pct=27.0 and wpa_delta_pct=+13.1, pre-play home WP = 27.0 - 13.1 = 13.9%); pre-play away WP = 100 - pre-play home WP. ALSO acceptable: WP derived from bbref `win_expectancy_pct` (in batting-team perspective per row) within 1pt rounding. The prose may flip the direction verbally ("swung 23.1 points toward Miami") — flag only when the magnitude is wrong by more than the rounding tolerance or the direction contradicts the sign on the home-team perspective.
- Pitching lines ("6.0 IP, 0 ER, 5 K, 4 BB", "7.0 scoreless innings with 10 strikeouts") → must match the `pitching_line` summary string in `top_performers` for that pitcher
- Batter lines ("3-for-4, 1 HR, 2 RBI", "went 2-for-4 with a double") → must match the `batting_line` summary string in `top_performers` for that batter
- Season totals attached to events ("his 11th homer", "homered (5)", "Schwarber's 16th HR") → must match `season_total` on the corresponding play in `key_swings` or `scoring_plays`
- Team records / streaks / L10 ("improved to 22-16", "four-game win streak", "8-2 L10", "W4") → must match `team_records.away` or `team_records.home`
- LEAGUE-WIDE comparisons ("league-best record", "second-worst in baseball", "tied with the Yankees for the AL lead", "leads the NL", "atop the majors") → must match the top-level `mlb_standings` array (passed once at the top of the user message, applies to all games). Verify by checking whether the claimed ranking actually holds across all 30 team rows. Do NOT flag league-wide claims that mlb_standings confirms; DO flag any league-wide claim that mlb_standings does not unambiguously support.
- WP / LP / SV pitcher names → must match `winning_pitcher` / `losing_pitcher` / `save_pitcher`
- Venue → must match `venue`
- Player names attached to events → must match a name in `key_swings`, `scoring_plays`, `top_performers`, `hardest_hit`, `top_pitches`, or the `batter`/`pitcher` fields of any `bbref.play_by_play` row
- Pitcher `game_score` claims ("78 game score", "his 64 game score") → must match `bbref.game_scores[pitcher_name]`
- Play chronology, runs-on-the-play, scorers ("R. Laureano scored on the sac fly", "two-run double in the fourth") → cross-check against `bbref.play_by_play` (`play_desc` text + `inning` ordering + `runs_outs` flag). If Savant and bbref disagree on whether a play scored runners, flag the claim.

CLAIMS THAT MUST BE FLAGGED AS FABRICATION (cannot be in the JSON):
- Player ages, multi-game streaks beyond what `team_records.streak` shows, season counting stats not in the data
- Forward-looking content: next opponent, travel day, next probable pitcher, scheduled game time
- Cross-game references ("second straight loss", "fourth consecutive home win") unless the `streak` field of `team_records` supports the exact count
- Direct citations to other media ("per ESPN", "MLB.com noted") — roundup runs on JSON only

CLAIMS THAT DO NOT NEED VERIFICATION:
- Contextual phrasing derivable from inning + outs + scoring_plays ("with two on", "in the bottom of the ninth", "loaded the bases", "two outs")
- Beat-writer color and metaphor ("dominated", "locked down", "set the tone", "powered past")
- Pitch sequencing or count info inferred from per-play data — only flag if directly contradicted
- Direct paraphrase of any play description in `scoring_plays[].description` or `key_swings[].description`
- General divisional standing phrasing if it matches the records ("leads the division", "atop the standings") when the team has the best record in its division per the records data

For each suspect claim, locate the supporting value if one exists nearby (prose may have rounded). Include the actual JSON value so the regenerator can correct it. Reference the game by `game_pk` so the runner knows which summary to rewrite.

Output STRICT JSON only (no prose around it, no markdown fences):
{
  "verdict": "pass" | "fail",
  "issue_count": <int>,
  "issues": [
    {
      "game_pk": <int>,
      "claim": "<exact phrase from the prose>",
      "category": "velocity|ev|wpa|score|pitching_line|batting_line|season_total|record|streak|name|venue|forward-looking|source-citation|other",
      "why_suspect": "<why this claim cannot be verified against the JSON>",
      "json_value_if_close": "<actual JSON value if the claim is close to a real one, else null>"
    }
  ]
}

Verdict is "pass" ONLY if issue_count == 0. Any unsupported claim → "fail".
"""


@dataclass
class FactCheckIssue:
    game_pk: int | None
    claim: str
    category: str
    why_suspect: str
    json_value_if_close: str | None = None

    def to_dict(self) -> dict:
        return {
            "game_pk": self.game_pk,
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

    def issues_by_game(self) -> dict[int, list[FactCheckIssue]]:
        out: dict[int, list[FactCheckIssue]] = {}
        for i in self.issues:
            if i.game_pk is None:
                continue
            out.setdefault(i.game_pk, []).append(i)
        return out

    def issue_summary(self) -> str:
        if not self.issues:
            return "(no issues)"
        return "\n".join(
            f"- [pk={i.game_pk} {i.category}] \"{i.claim}\" — {i.why_suspect}"
            + (f" (data: {i.json_value_if_close})" if i.json_value_if_close else "")
            for i in self.issues
        )


def _parse_factcheck_response(raw: str) -> FactCheckResult:
    """Parse the strict JSON the fact-checker is supposed to return.

    Defensive: if the response wraps the JSON in prose / fences, extract the
    first balanced JSON object.
    """
    if not raw:
        return FactCheckResult(
            verdict="fail",
            issues=[FactCheckIssue(
                game_pk=None, claim="(no response)", category="other",
                why_suspect="Fact-checker returned empty output",
            )],
            raw_response=raw,
        )

    cleaned = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(\{.*?\})\s*```\s*$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    else:
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
                game_pk=None, claim="(unparseable response)", category="other",
                why_suspect=f"Fact-checker output was not valid JSON: {e}",
            )],
            raw_response=raw,
        )

    verdict = (data.get("verdict") or "fail").strip().lower()
    issues_data = data.get("issues") or []
    issues: list[FactCheckIssue] = []
    for i in issues_data:
        if not isinstance(i, dict) or not i.get("claim"):
            continue
        pk_raw = i.get("game_pk")
        try:
            pk = int(pk_raw) if pk_raw is not None else None
        except (TypeError, ValueError):
            pk = None
        issues.append(FactCheckIssue(
            game_pk=pk,
            claim=str(i.get("claim", "")),
            category=str(i.get("category", "other")),
            why_suspect=str(i.get("why_suspect", "")),
            json_value_if_close=(
                str(i["json_value_if_close"])
                if i.get("json_value_if_close") not in (None, "", "null")
                else None
            ),
        ))
    if issues and verdict == "pass":
        verdict = "fail"
    return FactCheckResult(verdict=verdict, issues=issues, raw_response=raw)


def factcheck_summaries(
    summaries: dict[str, str],
    games_trimmed: list[dict],
    standings_trimmed: list[dict] | None = None,
) -> FactCheckResult:
    """Verify per-game summaries against their per-game JSON payloads.

    `summaries`: {game_pk_str: summary_text} — output of the generation step.
    `games_trimmed`: the same trimmed per-game payloads that were fed to the
       writer, so the fact-checker sees exactly what the writer saw.
    `standings_trimmed`: the same compact 30-team standings the writer saw,
       used to verify league-wide claims (league-best, AL lead, etc.).
    """
    if not summaries:
        return FactCheckResult(verdict="pass")  # nothing to verify

    pairs: list[dict] = []
    for game in games_trimmed:
        pk = game.get("game_pk")
        if pk is None:
            continue
        summary = summaries.get(str(pk)) or summaries.get(pk)
        if not summary:
            pairs.append({
                "game_pk": pk,
                "summary": "(missing — writer did not produce a summary for this game)",
                "json": game,
            })
            continue
        pairs.append({"game_pk": pk, "summary": summary, "json": game})

    standings_block = (
        "Full MLB standings (use to verify league-wide / cross-team claims):\n\n"
        f"```json\n{json.dumps(standings_trimmed, indent=2, default=str)}\n```\n\n"
    ) if standings_trimmed else ""

    user_message = (
        "Fact-check the following per-game summaries against their JSON payloads "
        "AND the full MLB standings. Game-specific claims must be verifiable from "
        "that game's `json` block; league-wide / cross-team claims must be "
        "verifiable from `mlb_standings`. Output STRICT JSON per the system "
        "prompt — no prose, no markdown fences.\n\n"
        "---\n\n"
        + standings_block
        + f"Per-game pairs:\n\n```json\n{json.dumps(pairs, indent=2, default=str)}\n```\n"
    )

    log.info(
        "Running fact-check on %d game summaries (%d chars)...",
        len(pairs), len(user_message),
    )
    try:
        text, in_toks, out_toks, _stop = _invoke_claude_cli(
            FACTCHECK_MODEL, FACTCHECK_SYSTEM_PROMPT, user_message
        )
    except Exception as e:
        log.error("Fact-check invocation failed: %s", e)
        return FactCheckResult(
            verdict="fail",
            issues=[FactCheckIssue(
                game_pk=None, claim="(fact-check call failed)", category="other",
                why_suspect=f"claude -p invocation raised: {e}",
            )],
        )

    result = _parse_factcheck_response(text or "")
    log.info(
        "Fact-check verdict: %s (%d issues, %d in / %d out tokens)",
        result.verdict, len(result.issues), in_toks, out_toks,
    )
    return result


# ---------------------------------------------------------------------------
# Standalone CLI for ad-hoc verification of an already-written roundup
# ---------------------------------------------------------------------------


def _parse_summaries_from_md(md_path: Path) -> dict[str, str]:
    """Extract per-game summaries from an existing roundup MD.

    Each game block looks like:
        ### [Marlins 5, Nationals 2 — venue](https://...gamePk=823868)

        <summary prose>

        | ... line score ... |

    We grab the prose between the header link (which contains the gamePk) and
    the next blank line / line-score table. Good enough for ad-hoc verification.
    """
    text = md_path.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    # ### [label](url with gamePk=NNN) followed by a blank line then summary text
    pattern = re.compile(
        r"^###\s+\[.+?\]\(https?://[^)]*?gamePk=(\d+)[^)]*\)\s*\n+"
        r"(.+?)(?=\n+\|)",
        re.MULTILINE | re.DOTALL,
    )
    for m in pattern.finditer(text):
        pk = m.group(1)
        summary = m.group(2).strip()
        out[pk] = summary
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Fact-check an MLB roundup MD")
    parser.add_argument("md_path", type=Path, help="Path to {date}_mlb-roundup.md")
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

    summaries = _parse_summaries_from_md(args.md_path)
    if not summaries:
        print(f"ERROR: no game summaries found in {args.md_path}", file=sys.stderr)
        return 2

    # Re-derive the per-game JSON the writer saw. Cheap: re-fetch the slate from
    # the same Savant gamefeed endpoint plus rebuild team-record augmentation.
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    from app.services.mlb_roundup import get_mlb_roundup
    from scripts.mlb_daily_roundup import (
        _trim_game_for_prompt,
        _trim_standings_for_prompt,
        build_record_map,
        fetch_rich_standings,
    )

    m = re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", args.md_path.read_text(), re.MULTILINE)
    if m:
        report_date = _date.fromisoformat(m.group(1))
    else:
        fm = re.match(r"^(\d{4}-\d{2}-\d{2})_", args.md_path.name)
        report_date = _date.fromisoformat(fm.group(1)) if fm else _date.today()

    game_date = report_date - _timedelta(days=1)
    standings = fetch_rich_standings()
    record_map = build_record_map(standings)
    games = get_mlb_roundup(game_date)
    for g in games:
        g["team_records"] = {
            "away": record_map.get(g.get("away_team") or "", {}),
            "home": record_map.get(g.get("home_team") or "", {}),
        }
    trimmed = [_trim_game_for_prompt(g) for g in games]
    trimmed_standings = _trim_standings_for_prompt(standings)

    result = factcheck_summaries(summaries, trimmed, trimmed_standings)

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
