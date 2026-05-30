# MLB Daily Roundup Process Doc

[[toc-levels:2]]
[[toc]]

## Why This Exists

The Cardinals digest covers one team in depth. The MLB roundup covers every game from yesterday at a glance: final scores (winner first), 3-4 sentence Claude-written summaries, line scores, top WPA swings, and current standings at the bottom. It exists for the days when nothing Cardinals-related is interesting but the rest of the league had walk-offs in three cities.

The roundup ships to a single Blot post per day, tagged `MLB` via the Dropbox folder structure (`Posts/MLB/`). It does **not** render to PDF, does **not** sync to Readdle, does **not** upload to the Fly.io volume. Blot only. Same separation as the Cardinals digest.

## How the Ecosystem Works

The MLB roundup shares almost everything with the Cardinals digest:

* Same 3 AM LaunchAgent runs both back-to-back from `scripts/daily_content_ingest.sh`.
* Same shared helpers: `_invoke_claude_cli` from `scripts/daily_analysis.py`; `linkify_players` + `load_player_links` from `app/services/player_linking.py`; `_defeat_blot_heading_titlecase` from `scripts/cardinals_daily_report.py`.
* Same Baseball Savant gamefeed primary source; same Baseball Reference cross-reference layer via `app/services/bbref_boxscore.py`.
* Same play annotation helpers from `app/services/play_annotations.py` (`rbi`, `season_total`).
* Same Opus 4.8 fact-checker pattern with surgical-edit retry loop and `MAX_FACTCHECK_ATTEMPTS = 6` cap.
* Same `--skip-factcheck` emergency bypass.
* Same accent-insensitive player linking, now Baseball Savant–first with a FanGraphs fallback when `mlbam_id` is missing (`Iván Herrera` matches DB form `Ivan Herrera`). Every occurrence is linked, not just the first.

### Standings team links

The team cell in each division standings row is rendered as a Baseball Savant team-page link (`https://baseballsavant.mlb.com/team/{team_id}`) using the MLBAM `team_id` already on each row from `fetch_rich_standings()`. Rows with no team ID fall back to plain text. Wrapping happens inline in `render_standings()` so no post-hoc linker is needed.

What differs:

* The roundup loops over **every regular-season game** for the date, not just one Cardinals game. A typical day produces 12-15 game payloads.
* The writer produces a **JSON dict** of per-game summaries plus one `post_summary` line, not a free-form markdown report. Python renders all data tables (standings, line scores, key-swing bullets) from structured data; Claude only writes the prose summary per game.
* The fact-checker verifies **all summaries in one batched call** keyed by `game_pk` and outputs issues tagged by game.
* The Blot post lives in `Posts/MLB/{date}-mlb-roundup.md` so it picks up the `MLB` tag via Blot's subfolder-as-tag convention.
* Standings live at the **bottom** of the post, not the top. NL Central leads the division order (per user preference), then NL East, NL West, AL East, AL Central, AL West.

## What It Produces

### Local markdown report

Path: `data/content/analysis/{YYYY-MM-DD}_mlb-roundup.md`

YAML frontmatter: `title`, `type: mlb-roundup`, `date`, `generated_at`, `game_count`, `input_tokens`, `output_tokens`.

Body:

1. `[Go to Standings](#standings)` jump link as the first line of body content, immediately under the H1. Anchors to the `## Standings` H2 at the bottom of the post. Emitted by `build_post_body()` on every run.
2. `## Games, {Month D, YYYY}` (the date is the game date, one day before the report date)
3. One H3 block per game, in chronological order by game start:
   * `### [Marlins 5, Nationals 2 at loanDepot park](savant_url)`. Winner-first AP convention, full header wrapped in a markdown link to the Savant gamefeed page.
   * 3-4 sentence Claude-written summary (post-fact-check)
   * Inning-by-inning line score table (extras append `(N inn)` to the header)
   * Decisions line: `WP: ... LP: ... SV: ...`
   * `**Key swings**` bullet list, top 4 by `|WPA Δ|`, each with inning, signed home-relative WPA delta, batter, event, pitcher, EV, pitch type, pitch velo
4. `## Standings` at the bottom, six H3 division tables (Team, W-L, PCT, GB, L10, Streak)

### Blot post

Path: `~/Library/CloudStorage/Dropbox-Brianrenshawmedia/Brian Renshaw/Apps/Blot/Posts/MLB/{YYYY-MM-DD}-mlb-roundup.md`

Blot frontmatter (the key:value form, not YAML):

```
Title: MLB Roundup, May 10, 2026
Date: 2026-05-11
Summary: <Claude-written one-line headline of the slate>
Link: mlb-roundup-2026-05-11
```

The `Posts/MLB/` subfolder gives the post an `MLB` tag via Blot's folder-as-tag behavior. The folder is auto-created on first run.

## How the Automation Works

### Daily cycle

The roundup runs as Step 4.45 of `scripts/daily_content_ingest.sh`, immediately after the Cardinals digest (Step 4.4) and before the PDF render (Step 4.5). On a Savant outage or unexpected error, the wrapper logs a warning and continues, so the rest of the daily pipeline does not break.

### Inside the MLB roundup step (Step 4.45)

The python script `scripts/mlb_daily_roundup.py` runs this sequence:

1. **Fetch rich standings** via `statsapi.get("standings", {"leagueId": "103,104", "hydrate": "team(division)"})` so every team row carries `wins`, `losses`, `pct`, `gb`, `streak` code, and `lastTen` split.
2. **Fetch per-game payloads** for yesterday via `app/services/mlb_roundup.py`. For each regular-season final on the date: get Savant gamefeed JSON, extract line score / key swings / scoring plays / top performers / hardest hit / top pitches / game context, fetch the bbref box score, annotate plays with `rbi` and `season_total`.
3. **Augment with team records.** Walk each game and attach `team_records.away` and `team_records.home` from the standings map so Claude can cite streaks and L10 records inline.
4. **Build the writer prompt.** Standings JSON for cross-team claims plus the per-game JSON array. Typical size: ~300k chars / ~75k input tokens (the bbref PBP per game is the bulk).
5. **Invoke Opus 4.8** via `_invoke_claude_cli`. The writer returns strict JSON: `{"post_summary": "...", "summaries": {"<game_pk>": "<3-4 sentence prose>", ...}}`.
6. **Fact-check all summaries** in one batched call (`factcheck_summaries` in `scripts/factcheck_mlb_roundup.py`, Opus 4.8). Each summary is checked against its own game's JSON plus the full standings, with bbref PBP as the secondary source.
7. **If fail:** apply a **surgical-edit retry**. The runner sends Claude (a) only the summaries that had flagged issues, (b) the specific phrase-level problems, and (c) instructions to return ONLY those summaries fixed (untouched games are preserved verbatim from the prior pass). Merge the retry's summaries on top of the previous ones and re-fact-check.
8. **Loop steps 6-7** up to `MAX_FACTCHECK_ATTEMPTS` (currently 6).
9. **If loop converges (pass):** Python renders the full post body (standings + game blocks). Write the local MD with frontmatter, then publish to Blot.
10. **If loop exhausts attempts:** quarantine to `data/content/analysis/factcheck_failed/{date}_mlb-roundup.md`. macOS notification fires. No Blot publish.

### Emergency bypass

`uv run python -m scripts.mlb_daily_roundup --skip-factcheck` skips the verification loop and publishes whatever Claude wrote. Use only when (a) the cron is stuck and (b) you have manually reviewed the draft.

## Why the writer / fact-checker split looks this way

### Why Python renders data and Claude only writes prose

Earlier versions had Claude assemble the entire post (standings tables, line scores, decisions, key swings, summaries). Every numeric in every table was a hallucination surface. Switching to "Python renders all data-driven tables, Claude only writes the per-game prose summary" eliminated 90% of the fact-check surface. The remaining 10% is the prose itself, which is what we actually want the model for.

### Why the fact-checker sees the full standings

A claim like "league-best 28-13 record" requires comparing across all 30 teams. The per-game `team_records` block only has the two teams playing each game. Without the full standings as additional context, the fact-checker has to flag every league-wide claim as unverifiable. With the full standings in scope, Claude can make league-wide claims that pass verification.

### Why WPA arithmetic is accepted within 0.5pt

Same reason as the Cardinals digest. Pre-play home WP = `home_wp_after_pct - wpa_delta_pct` is mathematically sound. Rejecting derived values forces Claude to cite only the post-play WP, which is unnatural prose ("a 24.1-point swing to 27.0%" vs "from 2.9% to 27.0%"). The fact-checker accepts both endpoints when they agree on arithmetic.

### Why surgical-edit retry instead of full regeneration

Full regeneration wastes tokens rewriting summaries that already passed, and the rewrite can introduce fresh inferences in paragraphs that previously had no issues. Surgical edits restrict Claude to the flagged claims only; the unflagged summaries are preserved verbatim from the prior pass. Each pass strictly shrinks the issue surface.

## Key Files

| File | Location | Purpose |
|---|---|---|
| `mlb_daily_roundup.py` | `scripts/` | Main runner. Fetches standings + per-game payloads, builds prompt, invokes Opus, loops fact-check + surgical edits, writes local MD, publishes to Blot |
| `factcheck_mlb_roundup.py` | `scripts/` | Opus 4.8 fact-checker for per-game summaries. Cross-references Savant + bbref + full standings. Standalone CLI available |
| `mlb_roundup.py` | `app/services/` | Per-game data builder. Walks the day's schedule, fetches Savant gamefeed + bbref for each game, annotates plays with `rbi` and `season_total` |
| `bbref_boxscore.py` | `app/services/` | Shared bbref scraper (also used by Cardinals digest) |
| `play_annotations.py` | `app/services/` | Shared play annotation helpers (also used by Cardinals digest) |
| `mlb_service.py` | `app/services/` | `get_standings()` + `get_schedule()` (also used elsewhere in the app) |
| `mlb_og_banner.py` | `app/services/` | Generates the per-post 1200×630 OG link-preview banner (MLB silhouette logo + date + game count). Invoked from `publish_to_blot()` |

## Outputs

| File | Location | Purpose |
|---|---|---|
| `{date}_mlb-roundup.md` | `data/content/analysis/` | Local archive of the day's roundup (post-factcheck-pass version) |
| `factcheck_failed/{date}_mlb-roundup.md` | `data/content/analysis/factcheck_failed/` | Quarantined draft (only present when fact-check loop exhausted) |
| `factcheck_failed/{date}_mlb-roundup.factcheck.json` | `data/content/analysis/factcheck_failed/` | Issue list for a quarantined draft |
| `{date}-mlb-roundup.md` | `~/Library/CloudStorage/Dropbox-Brianrenshawmedia/Brian Renshaw/Apps/Blot/Posts/MLB/` | The live Blot post (tagged `MLB` via the subfolder) |
| `_{date}-mlb-roundup.png` | `~/Library/CloudStorage/Dropbox-Brianrenshawmedia/Brian Renshaw/Apps/Blot/Posts/MLB/` | Per-post OG banner (sibling of the .md; underscore prefix keeps Blot from publishing it as a standalone photo post) |

## How to Run Operations

### Regenerate today's roundup

```
uv run python -m scripts.mlb_daily_roundup --force
```

`--force` regenerates even if today's MD already exists. Without it, the runner skips when the local MD is already on disk.

### Regenerate a specific date

```
uv run python -m scripts.mlb_daily_roundup --date 2026-05-10 --force
```

The covered game-slate is `--date` minus one day, matching the Cardinals digest convention.

### Dry run (no Claude call)

```
uv run python -m scripts.mlb_daily_roundup --date 2026-05-10 --dry-run
```

Renders a `*.dryrun.md` preview file with the layout but no Claude-generated summaries. Useful for verifying standings rendering and game-block structure without burning Opus quota.

### Emergency bypass fact-check

```
uv run python -m scripts.mlb_daily_roundup --date 2026-05-10 --force --skip-factcheck
```

Publishes whatever Claude wrote without verification. Use only after manual review.

### Recover from a quarantine

The MLB roundup does not have a separate `republish_to_blot.sh` since the post is rebuilt from structured data each run. To recover, either fix the writer prompt for the specific error class and re-run, or use `--skip-factcheck` after manually reviewing the quarantined draft.

## Known Quirks

* bbref blocks bare Python user agents. The scraper sends a desktop browser UA. If bbref ever blocks IP, swap UA or add jitter.
* bbref doubleheader URL convention: `0` for non-DH, `1` or `2` for split games. The runner derives this from the schedule's `doubleheader` and `game_num` fields.
* "Red Sox" vs "White Sox" both end in "Sox" — `_team_short` has explicit overrides so headers read "Red Sox" / "White Sox" rather than collapsing to "Sox".
* Some MLB team names disagree between MLB.com and bbref ("Athletics" / "OAK", "Los Angeles Angels" / "ANA", etc.). The mapping table `BBREF_CODE_FROM_MLB_NAME` handles all 30 teams.

## See Also

* `docs/cardinals-digest-process-doc.md` — the parent process doc; most operational mechanics (fact-check semantics, surgical-edit retry, accent-insensitive linking, Trust the Reader rules) are documented there in more detail.
* `docs/fantasy-baseball-system-process-doc.md` — system-level overview of all three morning artifacts (fantasy report, Cardinals digest, MLB roundup).
