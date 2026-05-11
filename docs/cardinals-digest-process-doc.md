# Cardinals Digest Process Doc

[[toc-levels:2]]
[[toc]]

## Why This Exists

The St. Louis Cardinals fan experience is fragmented. Game recaps live on MLB.com, Statcast detail lives at baseballsavant.mlb.com, beat-writer takes live in long-form posts at Viva El Birdos and The Cardinal Nation, and roster context lives in the Locked On St. Louis Cardinals podcast. Reading the Cardinals every morning meant opening four tabs, scrubbing through a 35-minute podcast for the two minutes that mattered, and still missing the per-pitch numbers that explain *why* the bullpen blew the lead.

Before this digest existed, the only Cardinals content in the fantasy baseball system was a single "Cardinals Corner" section embedded inside the larger fantasy report — a few hundred words written by Claude from the same fantasy-flavored prompt as the rest of the report. It was thin and it wasn't a beat-writer's voice.

This digest replaces that. Every morning a separate Cardinals-only report is generated, built from Baseball Savant gamefeed JSON (the same source MLB's broadcast graphics use), filtered through a strict fact-checker that rejects any numeric claim the data doesn't support, and published to a public blog at [cardinals.brianrenshaw.com](https://cardinals.brianrenshaw.com) (Blot.im, Dropbox-backed). The Cardinals digest is intentionally decoupled from the fantasy report — different audience, different scope, different output destinations.

## How the Ecosystem Works

The Cardinals digest is one of two morning report pipelines that share a foundation. Understanding what's shared and what isn't is essential before changing anything.

**Shared with the fantasy report:**

* The 3 AM LaunchAgent (`com.fantasybaseball.content-ingest`) runs both pipelines back-to-back from `scripts/daily_content_ingest.sh`.
* Blog and podcast ingestion (`scripts/blog_ingest.py`, `scripts/podcast_transcriber.py`, `scripts/transcript_collector.py`) — the same RSS plumbing that pulls FanGraphs and Pitcher List for fantasy also pulls Viva El Birdos, Redbird Rants, and the Locked On Cardinals podcast for this digest.
* `_invoke_claude_cli` in `scripts/daily_analysis.py` — both pipelines call this helper to invoke the bundled Claude Code binary under the user's Max subscription (no metered API spend).
* The 4 AM verifier (`scripts/verify_daily_ingest.sh`) checks artifacts from both pipelines.

**Cardinals-only — does not flow into the fantasy report's outputs:**

* `scripts/cardinals_daily_report.py` — the runner for this digest. Imports `_invoke_claude_cli` from `daily_analysis.py` but otherwise stands alone.
* `app/services/cardinals_postgame.py` — pulls the Baseball Savant `/gf?game_pk=...` gamefeed for the most recent Cardinals game and normalizes it into a single JSON payload.
* `scripts/factcheck_cardinals.py` — a second Claude call (Sonnet 4.6) that fact-checks the Score and Data section against the postgame JSON before publish.
* `scripts/republish_to_blot.sh` — recovery tool for republishing an existing local MD without regenerating it.
* The four `docs/cardinals-blot*.{css,html}` template files that style the Blot blog.

**Critical separation:** as of commit `fa1c804`, the Cardinals digest ships **to Blot only**. It does NOT render to PDF, does NOT sync to Readdle, and does NOT upload to the Fly.io volume. The fantasy report still does all three. If you find yourself adding a Cardinals MD to the Fly upload or a Cardinals PDF to Readdle, you've crossed the line that was deliberately drawn between the two systems.

```
                                ┌─────────────────────────────────┐
                                │       LaunchAgent: 3 AM Daily   │
                                │  scripts/daily_content_ingest   │
                                └──────────────┬──────────────────┘
                                               │
        ┌──────────────────────────────────────┼──────────────────────────────────────┐
        │                                      │                                      │
        ▼                                      ▼                                      ▼
┌──────────────────┐               ┌──────────────────────┐               ┌────────────────────────┐
│ Shared ingest    │               │ Fantasy report       │               │ Cardinals digest       │
│ - blog_ingest    │               │ daily_analysis.py    │               │ cardinals_daily_report │
│ - podcasts       │               │                      │               │ + factcheck_cardinals  │
│ - transcripts    │               │ → PDF (Cardinals     │               │ + cardinals_postgame   │
│ - Yahoo ETL      │               │   theme via md2pdf)  │               │                        │
└──────────────────┘               │ → Readdle iCloud     │               │ → Local MD             │
                                   │ → Fly.io volume      │               │ → Blot (Dropbox)       │
                                   └──────────────────────┘               │                        │
                                                                          │ (no PDF, no Readdle,   │
                                                                          │  no Fly upload)        │
                                                                          └────────────────────────┘
                                               │
                                               ▼
                                ┌──────────────────────────────────┐
                                │     LaunchAgent: 4 AM Daily      │
                                │  scripts/verify_daily_ingest     │
                                │  - checks both reports landed    │
                                │  - escalates factcheck_failed/   │
                                │  - macOS notification on fail    │
                                └──────────────────────────────────┘
```

## What It Produces

### Local markdown report

Path: `data/content/analysis/{YYYY-MM-DD}_cardinals-daily.md`

The date is the **report date** (the morning the digest is generated), not the game date — the covered game is the day before. Example: `2026-05-11_cardinals-daily.md` covers the May 10 game.

YAML frontmatter:

| Field | Example | Purpose |
|---|---|---|
| `title` | `"Cardinals Daily — May 11, 2026"` | Display title for the local archive |
| `type` | `cardinals-daily` | Slug used by other tools to identify the report type |
| `date` | `2026-05-11` | Report date (ISO) |
| `generated_at` | `2026-05-11T08:30:50+00:00` | UTC generation timestamp |
| `input_tokens` | `170443` | Tokens sent to Opus (includes retry totals on factcheck retry) |
| `output_tokens` | `8837` | Tokens received from Opus |

The body has six H2 sections in this exact order:

1. `## Score and Data for {Month D, YYYY}` — game story
2. `## Cardinals Notebook` — beat-writer roster/transactions/narrative analysis
3. `## Beat Writer's Verdict` — closing 2-3 paragraphs
4. `## Statcast Highlights` — appendix-style bullet list
5. `## Around the League` — 5-7 MLB-wide headline bullets (linked)
6. `## Interesting Analysis` — 4-6 deep-dive baseball pieces (linked)

Plus a `## Sources Analyzed` footer listing every Cardinals blog/podcast item that was fed to the prompt.

### Score and Data subsections (in order)

| Subsection | Source | Notes |
|---|---|---|
| Header line | `result`, `winning_pitcher`, `losing_pitcher`, `save_pitcher`, `venue`, `savant_url` | Bold matchup line ending in a link to the Savant gamefeed for the actual game |
| `### Line Score` | `line_score.innings`, `line_score.totals` | Markdown table, one column per inning + R / H / E totals |
| `### Cardinals Batters` | `boxscore.batters` + per-batter Statcast aggregates | Savant-style table: standard slash line PLUS Max EV, Hit Dist, xBA on Contact columns |
| `### Cardinals Pitchers` | `boxscore.pitchers` | IP / H / R / ER / BB / K / HR / Pitches / Decision |
| `### Game Analysis` | `wpa.key_swings`, `scoring_plays`, `game_context`, `wpa.top_wpa_players`, `statcast_highlights` | 4-5 paragraphs of beat-writer prose. Scout-flavored color (pitch sequences, count leverage, location reads) is embedded here, **not** in a separate bulleted Scout Notes section |
| `### Win Probability Swings` | `wpa.key_swings` | Top 4-5 plays by &#124;Δ WP&#124;, home-team-positive convention |

### Blot post

Path: `~/Library/CloudStorage/Dropbox-Brianrenshawmedia/Brian Renshaw/Apps/Blot/Posts/{YYYY-MM-DD}-cardinals-daily.md`

Blot watches this Dropbox folder; the post is live within seconds of being written. The Blot post is the same body as the local MD but with a different header (Blot uses `key: value` metadata, not YAML):

| Field | Example | Purpose |
|---|---|---|
| `Title` | `@ Padres 2-3 (L) — May 10` | Generated from postgame data — uses the game date, not today's date |
| `Date` | `2026-05-11` | Publish date (report date) |
| `Summary` | `Cardinals 2, San Diego Padres 3 at Petco Park.` | Homepage preview text |
| `Link` | `cardinals-daily-2026-05-11` | URL slug under blot |

Player names in the body are linkified to FanGraphs profiles via `linkify_players`. Zero-width spaces are inserted between adjacent uppercase letters inside heading lines (`### JJ Wetherholt` → `### J​J Wetherholt`) to defeat Blot's source-level small-caps title-casing of all-caps words.

### Fact-check JSON (only on retry-then-fail)

Path: `data/content/analysis/factcheck_failed/{YYYY-MM-DD}_cardinals-daily.factcheck.json`

Written only when the report fails fact-check twice. Lists every unsupported claim with category, why it's suspect, and the actual JSON value when one is close. Used by the 4 AM verifier to escalate.

```json
{
  "verdict": "fail",
  "issue_count": 2,
  "issues": [
    {
      "claim": "his 86 mph Sweeper retired Manny Machado on a .020 xBA flyout",
      "category": "name",
      "why_suspect": "lowest_xba_allowed pitch has no batter field naming Machado",
      "json_value_if_close": "{pitcher: Kyle Leahy, ... batter: null}"
    }
  ]
}
```

## How the Automation Works

### Daily cycle

| Time | Trigger | Step | What it does |
|---|---|---|---|
| 3:00 AM | LaunchAgent `com.fantasybaseball.content-ingest` | Step 1 | Collect MacWhisper transcripts finished overnight |
| 3:00 AM | (same) | Step 2 | Fetch RSS blogs (FanGraphs, Pitcher List, RotoWire, Viva El Birdos, Redbird Rants, The Cardinal Nation) |
| 3:00 AM | (same) | Step 3 | Download new podcast episodes (Locked On, In This League, CBS, FantasyPros, Locked On Cardinals, Wednesday With Walton and Reis) |
| 3:00 AM | (same) | Step 3.5 | Yahoo ETL refresh (rosters + standings — fantasy only, but runs first) |
| 3:00 AM | (same) | Step 4 | Generate fantasy daily intel report via Opus 4.7 |
| 3:00 AM | (same) | Step 4.4 | **Generate Cardinals digest** — see "How the Game-Narrative Pipeline Works" |
| 3:00 AM | (same) | Step 4.5 | Render fantasy MD to PDF via `md2pdf cardinals` (Cardinals MD intentionally **not** rendered) |
| 3:00 AM | (same) | Step 4.6 | Copy fantasy PDF to Readdle iCloud folder |
| 3:00 AM | (same) | Step 5 | Upload fantasy markdowns to Fly.io volume (Cardinals MD intentionally **excluded** by `case "$BASENAME" in *cardinals-daily*) continue ;;`) |
| 4:00 AM | LaunchAgent `com.fantasybaseball.verify-ingest` | All checks | Inspects artifacts from both pipelines; macOS notification + log entry on any FAIL |

The full launchd schedule is in two plist files, both at `~/Library/LaunchAgents/`:

* `com.fantasybaseball.content-ingest.plist` — 3 AM daily, runs `daily_content_ingest.sh`
* `com.fantasybaseball.verify-ingest.plist` — 4 AM daily, runs `verify_daily_ingest.sh`
* `com.fantasybaseball.transcript-watcher.plist` — always running, monitors MacWhisper output (shared with fantasy)

Log files for each run land under `data/content/logs/`:

| Log file | Written by | Purpose |
|---|---|---|
| `ingest_{date}.log` | `daily_content_ingest.sh` | Full 3 AM pipeline output (tee'd at the top of the script) |
| `verify_problems.log` | `verify_daily_ingest.sh` | Append-only log of any check failures with timestamp |
| `last_verified.txt` | `verify_daily_ingest.sh` | One-line PASS/FAIL summary for today |
| `launchd_stdout.log` / `launchd_stderr.log` | launchd | Raw stdout/stderr from the ingest job (rarely useful — the tee'd ingest log is better) |

### Inside the Cardinals step (Step 4.4)

The python script `scripts/cardinals_daily_report.py` runs this sequence:

1. **Fetch postgame data** for yesterday (`get_cardinals_postgame(today - 1)` from `app/services/cardinals_postgame.py`). Primary source: Baseball Savant `/gf?game_pk=...` gamefeed JSON. Fallback: `pybaseball.statcast_single_game()` if the gamefeed produces zero highlights. Returns `None` on a Cardinals off-day.
2. **Load Cardinals content** from `data/content/blogs/` and `data/content/transcripts/` over a 5-day window, filtered by source key prefix in the filename (`{date}_viva_el_birdos_*.md`, etc.).
3. **Fetch MLB news headlines** (ESPN MLB + MLB.com RSS) for the Around the League section.
4. **Fetch analysis headlines** from 9 baseball/fantasy feeds for the Interesting Analysis section.
5. **Build the user prompt** — system prompt + section instructions + postgame JSON + Cardinals content + MLB headlines + analysis headlines. Typical size: ~170k chars / ~44k tokens.
6. **Invoke Opus 4.7** via `_invoke_claude_cli` (Max subscription, no API spend). Timeout 1800s with one retry on `subprocess.TimeoutExpired`.
7. **Fact-check** the generated Score and Data section against the postgame JSON (`factcheck_score_and_data` in `scripts/factcheck_cardinals.py`, Sonnet 4.6).
8. **If fail:** regenerate ONCE with the issues appended to the prompt as explicit corrections. Re-fact-check.
9. **If still fail:** quarantine the MD + issues JSON to `data/content/analysis/factcheck_failed/`. Fire a macOS notification. Skip Blot publish. Local clean MD is NOT written.
10. **If pass:** write the local MD with frontmatter + sources footer, then `_publish_to_blot()` writes the Blot post to the Dropbox folder.

### Recovery path

If the local MD exists but the Blot post didn't land (Dropbox paused, write failure), use `scripts/republish_to_blot.sh [DATE]`. Defaults to today; pass `2026-05-10` to republish a specific date. It re-derives the postgame data and reuses the existing local MD verbatim — no Opus regeneration, no quota burn.

## How the Game-Narrative Pipeline Works

This is the part that makes the digest worth the bytes. Three design decisions earn their space.

### Why we drive the narrative from Baseball Savant gamefeed JSON

Earlier versions used `pybaseball.statcast(team='STL')`, which hits the Statcast search CSV endpoint and only returns the half-innings where STL is pitching. Every hitter Statcast value was missing. We switched to `pybaseball.statcast_single_game(game_pk)`, which returns both halves correctly — but it still lagged the public Savant page by 4-6 hours, so 3 AM runs frequently produced empty Statcast highlights for late West Coast games.

The current primary source is `https://baseballsavant.mlb.com/gf?game_pk={pk}` — the JSON endpoint MLB's own Gameday graphics consume. It's populated within minutes of a game ending. It also exposes data the CSV doesn't: scoring-play descriptions, win-probability per AB, MLB's curated `topPerformers` block, weather/attendance/IBB/inherited runners. The CSV-search endpoint remains as a fallback (`_fetch_savant_gamefeed` returns no highlights → fall through to `pybaseball.statcast_single_game`), but it almost never fires anymore.

### Why the prompt names specific fields, and why scoring_plays + wpa.key_swings agree

The postgame payload exposes the gamefeed data in eight buckets:

| Bucket | Built from | What it's for |
|---|---|---|
| `line_score` | `statsapi.get('game_linescore')` | Per-inning runs/hits/errors. Source of the Line Score table |
| `boxscore.batters` / `boxscore.pitchers` | `statsapi.boxscore_data` | Standard slash + IP lines. Batters also carry Max EV / Hit Dist / xBA-on-Contact via `_batter_statcast_aggregate` |
| `scoring_plays` | gamefeed `team_home`/`team_away` filtered by `des` containing "score" | Chronological scoring sequence with batter/pitcher/EV/xBA/pitch-velo |
| `wpa.key_swings` | gamefeed `scoreboard.stats.wpa.gameWpa` sorted by &#124;Δ&#124; | Top 6 at-bats by win-probability swing |
| `wpa.top_wpa_players` / `wpa.last_plays` | gamefeed `topWpaPlayers`, `lastPlays` | Cumulative game contributors + closing-sequence color |
| `top_performers` | gamefeed `boxscore.topPerformers` | MLB's own curated standouts with verbatim stat-line strings |
| `game_context` | gamefeed `boxscore.info` + `scoreboard` | Weather, wind, attendance, game-time, ABS challenges, IBB note, walk-off final-play description, linescore note ("One out when winning run scored") |
| `statcast_highlights` | gamefeed pitch streams aggregated by `_highlights_from_gamefeed` | Hardest hit / best xBA / barrels / top velocity / top whiffs / best putaways / lowest xBA allowed — every pitcher-side bucket carries `batter_name` so the prompt can verifiably pair pitchers with the specific batter they faced |

Both `scoring_plays` and `wpa.key_swings` pick the **AB-ending pitch** (highest `pitch_number` within the at-bat). This wasn't always true — an earlier version of `_scoring_plays_from_gamefeed` picked the first pitch in the AB with a `des` populated, producing velocity values that disagreed with `wpa.key_swings` for the same plate appearance. The fact-checker correctly flagged it. Commit `29ca6fb` aligned both extractors.

The prompt's Game Analysis instructions explicitly tell the model that `wpa.key_swings` is "THE narrative spine" — the +48.5% game-tying swing is the *moment* the game pivoted, not just one of many homers — and to reference at least four key swings by name and metric. The prompt also forbids blog/podcast citations in the Score and Data section: source attribution belongs in Cardinals Notebook, not the game story.

### Why fact-check, and why one retry then block

Beat-writer prose is exactly the kind of writing that drifts: a 99.4 mph fastball gets rounded to 99 mph, then to "high-90s heat", then to "triple-digit heat" two paragraphs later. The model can hallucinate a batter into a `lowest_xba_allowed` row that only names the pitcher. Cumulative season-long stats ("his MLB co-lead in saves") are not in the postgame payload at all and cannot be verified.

The fact-checker is a separate Sonnet 4.6 call with a strict system prompt that enumerates every verifiable claim category (velocity, EV, distance, xBA, spin, LA, WPA, score, pitching_line, name-event pairing) plus categories that must be flagged as fabrication (player ages, multi-game streaks, forward-looking content, blog citations in this section). It outputs strict JSON with verdict, issue_count, and per-issue category + reasoning. The runner parses that JSON.

The retry semantics are deliberate. **Retry once with the issues fed back to the original prompt** — a single round of correction usually resolves rounding and pairing errors. **Block on second failure** — if the model still can't ground its claims after explicit correction, the report is quarantined, not published. The user explicitly chose "block everything on failure" over "warn-and-ship": bad numbers on the public blog are worse than a missed day.

On a fact-check block:

* The clean MD path (`data/content/analysis/{date}_cardinals-daily.md`) is NOT written, so the bash downstream glob in `daily_content_ingest.sh` finds nothing to upload.
* The failing MD is written to `data/content/analysis/factcheck_failed/{date}_cardinals-daily.md`, alongside `{date}_cardinals-daily.factcheck.json`.
* A macOS notification fires immediately ("Cardinals report BLOCKED").
* The 4 AM verifier escalates: a quarantine directory entry causes the verifier to fail with `Cardinals fact-check passed — 0` and a second notification.

To recover from a block, hand-edit the quarantined MD using the issues JSON as the punch list, then re-verify standalone:

```
uv run python -m scripts.factcheck_cardinals \
  data/content/analysis/factcheck_failed/{date}_cardinals-daily.md
```

When that passes, `mv` the file out of `factcheck_failed/` into `analysis/` and run `scripts/republish_to_blot.sh {date}`.

## Key Files

### Scripts and services

| File | Location | Purpose |
|---|---|---|
| `cardinals_daily_report.py` | `scripts/` | Main runner. Loads content, fetches postgame, builds prompt, invokes Opus, runs fact-check, retries once, writes local MD, publishes to Blot |
| `factcheck_cardinals.py` | `scripts/` | Sonnet-based fact-checker. Standalone CLI for ad-hoc verification; importable by the runner. Reads report date from frontmatter or filename prefix |
| `cardinals_postgame.py` | `app/services/` | Builds the postgame JSON payload from Savant gamefeed + statsapi boxscore + line score. Fallback to pybaseball |
| `republish_to_blot.sh` | `scripts/` | Recovery: re-publishes an existing local MD to Blot without regenerating it. Defaults to today; takes optional `YYYY-MM-DD` arg |
| `daily_content_ingest.sh` | `scripts/` | Shared 3 AM wrapper. Step 4.4 invokes the Cardinals runner; Steps 4.5/4.6/5 exclude the Cardinals MD by design |
| `verify_daily_ingest.sh` | `scripts/` | 4 AM verifier. Checks local Cardinals MD exists (soft), Blot post landed (hard), no quarantined report (hard) |
| `blog_ingest.py` | `scripts/` | Shared RSS fetcher. Cardinals-specific feed keys: `viva_el_birdos`, `redbird_rants`, `cardinal_nation` |
| `podcast_transcriber.py` | `scripts/` | Shared podcast downloader. Cardinals-specific feed keys: `locked_on_cardinals`, `walton_and_reis` |

### Templates and styling

| File | Location | Purpose |
|---|---|---|
| `cardinals-blot.css` | `docs/` | Cardinals-themed CSS for the Blot blog (drop into Blot template editor) |
| `cardinals-blot-head.html` | `docs/` | Blot `head.html` template (loads fonts + CSS) |
| `cardinals-blot-entries.html` | `docs/` | Blot homepage entries template |
| `cardinals-blot-archives.html` | `docs/` | Blot archives template |

### LaunchAgents

| File | Location | Purpose |
|---|---|---|
| `com.fantasybaseball.content-ingest.plist` | `~/Library/LaunchAgents/` | 3 AM daily — runs the shared ingest script |
| `com.fantasybaseball.verify-ingest.plist` | `~/Library/LaunchAgents/` | 4 AM daily — runs the verifier |

A copy of each plist also lives at `/Users/brianrenshaw/Projects/` for editing convenience. The `~/Library/LaunchAgents/` copies are the ones launchd actually loads.

### Outputs

| File | Location | Purpose |
|---|---|---|
| `{date}_cardinals-daily.md` | `data/content/analysis/` | Local archive of the day's digest (post-factcheck-pass version) |
| `factcheck_failed/{date}_cardinals-daily.md` | `data/content/analysis/factcheck_failed/` | Quarantined draft (only present when fact-check failed twice) |
| `factcheck_failed/{date}_cardinals-daily.factcheck.json` | `data/content/analysis/factcheck_failed/` | Issue list for a quarantined draft |
| `{date}-cardinals-daily.md` | `~/Library/CloudStorage/Dropbox-Brianrenshawmedia/Brian Renshaw/Apps/Blot/Posts/` | The live Blot post |

### Documentation

| File | Location | Purpose |
|---|---|---|
| `cardinals-digest-process-doc.md` | `docs/` | This file — operations + handoff |
| `CARDINALS_DAILY_REPORT.md` | `docs/` | Architectural reference: prompt design, content sources rationale, troubleshooting recipes |
| `fantasy-baseball-system-process-doc.md` | `docs/` | Sibling process doc for the fantasy report system |

### Management URLs

* Blog (public): [cardinals.brianrenshaw.com](https://cardinals.brianrenshaw.com)
* Blot admin: [blot.im](https://blot.im) (login with the account that owns the Dropbox-linked blog)
* GitHub repo: [github.com/brianrenshaw/caught_stealing](https://github.com/brianrenshaw/caught_stealing)
* Baseball Savant gamefeed (for verifying source data): `https://baseballsavant.mlb.com/gamefeed?date=YYYY-MM-DD&gamePk={id}`

## Directory Layout

```
fantasy_baseball_br/
├── scripts/
│   ├── cardinals_daily_report.py        # Main runner
│   ├── factcheck_cardinals.py           # Sonnet fact-checker (also standalone CLI)
│   ├── republish_to_blot.sh             # Recovery: re-push existing MD to Blot
│   ├── daily_content_ingest.sh          # Shared 3 AM wrapper (Step 4.4 = Cardinals)
│   ├── verify_daily_ingest.sh           # Shared 4 AM verifier
│   ├── blog_ingest.py                   # Shared RSS fetcher (3 Cardinals feeds)
│   └── podcast_transcriber.py           # Shared podcast downloader (2 Cardinals feeds)
├── app/services/
│   └── cardinals_postgame.py            # Savant gamefeed → JSON payload
├── data/content/
│   ├── analysis/
│   │   ├── {date}_cardinals-daily.md    # Daily output, post-factcheck-pass
│   │   └── factcheck_failed/            # Quarantined drafts + issue JSON
│   ├── blogs/                           # Source: {date}_{source}_{slug}.md
│   ├── transcripts/                     # Source: {date}_{source}_{slug}.md
│   └── logs/
│       ├── ingest_{date}.log            # Tee'd output of the 3 AM pipeline
│       ├── verify_problems.log          # Append-only verifier failure log
│       └── last_verified.txt            # One-line PASS/FAIL summary
└── docs/
    ├── cardinals-digest-process-doc.md  # This file
    ├── CARDINALS_DAILY_REPORT.md        # Architectural reference
    ├── cardinals-blot.css               # Blot template CSS
    ├── cardinals-blot-head.html
    ├── cardinals-blot-entries.html
    └── cardinals-blot-archives.html

~/Library/CloudStorage/Dropbox-Brianrenshawmedia/Brian Renshaw/Apps/Blot/
└── Posts/
    └── {date}-cardinals-daily.md        # Live Blot post (one per day)

~/Library/LaunchAgents/
├── com.fantasybaseball.content-ingest.plist   # 3 AM daily
└── com.fantasybaseball.verify-ingest.plist    # 4 AM daily
```

## How to Run Operations

### Trigger the full automation manually (now)

```
launchctl kickstart -k gui/$(id -u)/com.fantasybaseball.content-ingest
```

This runs the same script launchd will run at 3 AM. Logs go to `data/content/logs/ingest_{today}.log` and the `tee` in the script also writes there.

### Regenerate just today's Cardinals digest (skip fantasy)

```
uv run python -m scripts.cardinals_daily_report --force
```

`--force` overwrites today's MD. The fact-checker still gates the publish; on quarantine, you'll see `Cardinals report BLOCKED` macOS notification and the failing MD lands in `factcheck_failed/`.

### Regenerate a historical day

```
uv run python -m scripts.cardinals_daily_report --force --date 2026-05-10
```

The `--date` flag overrides "today" for the report-date stamp; the covered game is `date - 1`. Same pipeline (Opus → fact-check → retry → publish-or-quarantine).

### Run a fact-check standalone on an existing MD

```
uv run python -m scripts.factcheck_cardinals \
  data/content/analysis/2026-05-11_cardinals-daily.md
```

Re-fetches the postgame payload (the date is parsed from frontmatter; if missing, from the filename prefix) and asks Sonnet to verify the Score and Data section against it. Prints verdict + issue list. Useful after hand-editing a quarantined draft.

`--json` flag emits the strict JSON output instead of human-readable text.

### Re-publish to Blot without regenerating (recovery)

```
./scripts/republish_to_blot.sh                 # today's MD
./scripts/republish_to_blot.sh 2026-05-10      # specific date
```

Reads the existing local MD and pushes it to Blot. Use when:

* The 3 AM run wrote the MD but Blot publish failed (Dropbox paused / unmounted / transient write error)
* You manually edited the local MD and want to push the corrected version
* You hand-fixed a quarantined report after moving it back to the canonical path

### View logs

```
# Most recent 3 AM run
less data/content/logs/ingest_$(date +%Y-%m-%d).log

# Just the Cardinals step from the most recent run
grep -A 200 "Cardinals Daily Report" data/content/logs/ingest_$(date +%Y-%m-%d).log

# Verifier history of failures
cat data/content/logs/verify_problems.log

# Today's verifier verdict
cat data/content/logs/last_verified.txt
```

### Check launchd job status

```
launchctl print gui/$(id -u)/com.fantasybaseball.content-ingest | grep -E "state|last exit code"
launchctl print gui/$(id -u)/com.fantasybaseball.verify-ingest   | grep -E "state|last exit code"
```

### Reload a LaunchAgent after editing its plist

```
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.fantasybaseball.content-ingest.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.fantasybaseball.content-ingest.plist
```

## How to Modify

### Add a new Cardinals content source

1. **If it's a blog with RSS:** add the entry to `RSS_FEEDS` in `scripts/blog_ingest.py` (around line 36) with the existing schema:

   ```python
   "my_new_blog": {
       "name": "My New Cardinals Blog",
       "url": "https://example.com/feed",
       "type": "rss",
   },
   ```

   Then add the feed key to `CARDINALS_SOURCES` in `scripts/cardinals_daily_report.py` (around line 70) so the Cardinals runner picks up its files from `data/content/blogs/`.

2. **If it's a podcast:** add to `PODCAST_FEEDS` in `scripts/podcast_transcriber.py` (around line 46). Then add the key to `CARDINALS_SOURCES`. The transcript watcher will pick up MacWhisper output automatically.

3. **Test the fetch:** `uv run python -m scripts.blog_ingest --feed my_new_blog --days 7 --max-articles 5` (or `--feed` on `podcast_transcriber`). Confirm files land in `data/content/blogs/` (or `transcripts/`) with the expected `{date}_my_new_blog_{slug}.md` filename.

### Change the section order

The section list is enforced in two places in `scripts/cardinals_daily_report.py`:

1. `build_prompt()` (around line 564) — the opening directive enumerates the six H2 sections in order
2. `SECTION_INSTRUCTIONS` (around line 383) — the long inline string with per-section detail

If you change one, change both. The `SECTION_INSTRUCTIONS` text also drives subsection ordering inside Score and Data; the fact-checker doesn't enforce structure, only content fidelity, so a wrong section order will quietly ship if the prompt doesn't catch it.

### Change the schedule

Edit `~/Library/LaunchAgents/com.fantasybaseball.content-ingest.plist`, change the `Hour` / `Minute` values under `StartCalendarInterval`, and reload (see "Reload a LaunchAgent" above). Same for the verifier plist. Keep them at least 30 minutes apart so the verifier always runs after the ingest finishes.

### Update the Blot template styling

Edit `docs/cardinals-blot.css`. Then paste the file content into the Blot template editor at [blot.im](https://blot.im) → your blog → Templates. Same for `cardinals-blot-head.html`, `cardinals-blot-entries.html`, `cardinals-blot-archives.html`. There is no automatic deploy — Blot's template files are managed in their web editor, not the Dropbox sync.

### Change the fact-checker strictness

The system prompt in `scripts/factcheck_cardinals.py` (line 34) is where the strictness lives. The "MUST BE VERIFIED" and "MUST BE FLAGGED" lists drive what gets caught. The "DO NOT NEED VERIFICATION" list defines acceptable beat-writer color — adding to this list reduces false positives at the cost of letting more drift through.

To switch the model: change `FACTCHECK_MODEL` at the top of the file (currently `claude-sonnet-4-6`). Opus is slower but catches subtler contradictions; Sonnet is faster and catches everything we've seen in practice. The user is on Max 20x — quota is sunk cost, so model choice is purely a runtime decision.

### Disable the fact-check gate

Don't. The fact-checker has caught real fabrications on every regen the team has run. If you must disable it temporarily, comment out the block in `cardinals_daily_report.py` between the `factcheck = factcheck_score_and_data(...)` call and `if not factcheck.passed:` — the report will write directly and publish to Blot without verification. **Do not commit that change.**

## Known Quirks and Edge Cases

### Blot title-cases all-caps words inside heading tags

A heading like `### JJ Wetherholt` becomes `### <span class="small-caps">Jj</span> Wetherholt` on Blot. The `_defeat_blot_heading_titlecase()` function in `cardinals_daily_report.py` inserts a zero-width space (U+200B) between adjacent uppercase letters inside heading lines so Blot's word-boundary detection skips them. The character is invisible in rendered HTML. URL contents inside `(...)` are preserved (the function splits on parenthesized text before transforming).

If you see `Jj Wetherholt` or `Mlb Cardinals` rendering on the live blog, the ZWSP step didn't run for that publish path — most likely you wrote directly to the Blot Posts folder without going through `_publish_to_blot`.

### scoring_plays and wpa.key_swings must agree on pitch velocity

Both buckets describe the same plate appearances. They pick the AB-ending pitch (highest `pitch_number`). If you change one extractor, change the other — the fact-checker WILL flag the disagreement and the report WILL fail. Commit `29ca6fb` fixed this once already.

### sftp put silently skips existing remote files

Fantasy report uploads to Fly use `flyctl ssh sftp shell` with `put`. If the destination file already exists, sftp skips the transfer instead of overwriting. The script handles this by running `flyctl ssh console -C "rm -f ..."` before each put. Cardinals isn't affected (we don't upload to Fly anymore), but the pattern is documented because it bit us with the fantasy report. Do NOT remove the pre-delete step in `daily_content_ingest.sh` Step 5.

### pybaseball CSV endpoint lags the gamefeed

Earlier versions used `pybaseball.statcast(team='STL')` (CSV-search endpoint) and frequently saw empty Statcast highlights for late West Coast games at 3 AM. The current code uses the Savant gamefeed JSON as primary. pybaseball remains as a fallback. If a Cardinals report shows "Statcast highlight detail unavailable" but the Savant gamefeed page clearly has data, `_fetch_savant_gamefeed` may be failing — check the ingest log for "Savant gamefeed attempt N/3 failed" warnings.

### Fact-checker fetches the wrong game's data when frontmatter is missing

The standalone fact-checker CLI reads the report date from frontmatter. Quarantined drafts have NO frontmatter (they're written before the frontmatter wrap step). The CLI's fallback now parses the date from the filename prefix (`2026-05-10_cardinals-daily.md` → 2026-05-10). If you ever rename a quarantined MD without preserving that ISO prefix, you'll get fact-checked against today's game instead of the file's game.

### Blot's tag rendering doesn't match the template's Mustache variable

When this was first set up, every attempt to render tag chips in the entries template produced empty tags or the post filename. None of `{{name}}`, `{{tag}}`, `{{slug}}` worked. The fix was to remove tag iteration entirely and use the `Summary` metadata for homepage preview text. Don't try to reintroduce tags without testing carefully against Blot's actual variable resolution behavior.

### Cardinals off days return None

`get_cardinals_postgame` returns `None` if no STL game played on the target date. The prompt template handles this — it produces a "(no game)" header and pivots to the most recent game discussed in the expert content. Be aware: the fact-checker is more lenient on off-day reports because there's less data to verify against, but it still rejects fabricated numbers.

### Spring training games are filtered out

`_find_stl_game` filters by `game_type == "R"` (regular season only). If you ever want to cover spring training or postseason, change that filter — but the gamefeed schema can differ for non-regular games and the boxscore parsers may need fixes.

## If You Are Setting This Up From Scratch

Order matters. Skipping a step here will silently fail later in unhelpful ways.

### Prerequisites

* **macOS** with launchd (this pipeline is macOS-only by design — the LaunchAgents drive everything)
* **Python 3.12+** and `uv` package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
* **Node.js** (for `md2pdf`, used by the fantasy report — not Cardinals, but the shared ingest script imports it)
* **Claude Code CLI** bundled with the VSCode extension at `~/.vscode/extensions/anthropic.claude-code-*-darwin-arm64/resources/native-binary/claude`. The runner auto-locates this.
* **Anthropic Max 20x subscription** signed in via the VSCode extension. The `claude -p` invocations draw from this quota, not the metered API. (The `ANTHROPIC_API_KEY` env var is *explicitly scrubbed* by `_invoke_claude_cli` to force the subscription path.)
* **Dropbox** installed and signed into the account that owns the Blot blog. The `Apps/Blot/Posts/` folder must exist under your Dropbox root.
* **Blot.im account** with a Dropbox-linked blog and a custom domain configured.
* **MacWhisper** (for podcast transcripts — shared with the fantasy pipeline). Configure the watch folder at `data/content/audio/pending/` and output to `data/content/audio/transcribed/`.

### Step-by-step

1. **Clone the repo and install dependencies.**

   ```
   git clone https://github.com/brianrenshaw/caught_stealing.git fantasy_baseball_br
   cd fantasy_baseball_br
   uv sync
   ```

2. **Create the directory tree** if it doesn't exist:

   ```
   mkdir -p data/content/{blogs,transcripts,analysis,analysis/factcheck_failed,audio/pending,audio/transcribed,logs}
   ```

3. **Configure the Blot Dropbox folder path.** Confirm `BLOT_POSTS_DIR` in `scripts/cardinals_daily_report.py` matches your Dropbox path. If your Dropbox account name differs, edit the constant.

4. **Apply the Blot templates.** Open Blot's web editor → your blog → Templates. Replace each template's content with the matching file from `docs/`: `cardinals-blot.css` → `style.css`, `cardinals-blot-head.html` → `head.html`, `cardinals-blot-entries.html` → `entries.html`, `cardinals-blot-archives.html` → `archives.html`.

5. **Bootstrap content.** Run the blog and podcast ingestion at least once so the Cardinals digest has source material:

   ```
   uv run python -m scripts.blog_ingest --days 7 --max-articles 10
   uv run python -m scripts.podcast_transcriber --days 7 --max-episodes 5
   ```

   Wait for MacWhisper to finish transcribing, then:

   ```
   uv run python -m scripts.transcript_collector
   ```

6. **Test the postgame fetcher.** Pick a recent date with a Cardinals game:

   ```
   uv run python -m app.services.cardinals_postgame 2026-05-10
   ```

   You should see a JSON dump with `line_score`, `boxscore`, `statcast_highlights`, `scoring_plays`, `wpa`, etc. populated. If `statcast_highlights` is `{}`, the gamefeed fetch failed or the game hasn't been published yet.

7. **Run the Cardinals digest manually.**

   ```
   uv run python -m scripts.cardinals_daily_report --force
   ```

   Watch the log output. You're looking for `Fact-check PASSED` and `Published to Blot: ...`. If you see `quarantined`, the fact-checker rejected the draft — inspect `data/content/analysis/factcheck_failed/{date}_cardinals-daily.factcheck.json` for the issues.

8. **Verify the Blot post landed.** Open Dropbox `Apps/Blot/Posts/` and confirm the file exists. Wait 30 seconds, then visit your Blot blog homepage. The new post should appear.

9. **Install the LaunchAgents.**

   ```
   cp /Users/brianrenshaw/Projects/com.fantasybaseball.content-ingest.plist ~/Library/LaunchAgents/
   cp /Users/brianrenshaw/Projects/com.fantasybaseball.verify-ingest.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.fantasybaseball.content-ingest.plist
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.fantasybaseball.verify-ingest.plist
   ```

   You may need to grant `launchd` Full Disk Access in System Settings → Privacy & Security so it can write into the Dropbox folder.

10. **Test a launchd kick.**

    ```
    launchctl kickstart -k gui/$(id -u)/com.fantasybaseball.content-ingest
    ```

    Tail the log: `tail -f data/content/logs/ingest_$(date +%Y-%m-%d).log`. Wait for "Content ingest finished:".

11. **Done.** The 3 AM run will fire from now on. The 4 AM verifier will tell you (via macOS notification) if anything fails.

## History

| Date | Change |
|---|---|
| 2026-04-XX | Initial Cardinals digest pipeline shipped. Single `cardinals-daily.md` per day with postgame data via `pybaseball.statcast`. Cardinals-themed PDF rendered and synced alongside fantasy report. |
| 2026-05-09 | Switched primary Statcast source from `pybaseball.statcast(team='STL')` to `pybaseball.statcast_single_game(game_pk)` — fixed hitter-side highlights being silently dropped. |
| 2026-05-10 | Migration to Baseball Savant `/gf?game_pk=...` JSON endpoint as the primary source. pybaseball moved to fallback only. Commit `d37a11f`. |
| 2026-05-11 | Added gamefeed-driven `scoring_plays`, `wpa.key_swings`, `top_performers`, `game_context` extractors. Per-batter Statcast aggregates rolled into box-score rows. Win Probability Swings table introduced. Commit `aa41e30`. |
| 2026-05-11 | Section order changed: Game Analysis moved ahead of Statcast/WPA inside Score and Data; Scout Notes deleted (scout color absorbed into Game Analysis prose). Commit `427447d`. |
| 2026-05-11 | Fact-checker added (`scripts/factcheck_cardinals.py`). Sonnet 4.6 verifies the Score and Data section against POSTGAME DATA JSON. Retry-once-then-quarantine semantics. Commit `180a45b`. |
| 2026-05-11 | Fixed `_scoring_plays_from_gamefeed` to pick the AB-ending pitch so it agrees with `wpa.key_swings`. Added `--date` flag for historical regenerations. Commit `29ca6fb`. |
| 2026-05-11 | Section order changed again: Statcast Highlights moved out of Score and Data into its own H2 between Beat Writer's Verdict and Around the League. Commit `c6fa302`. |
| 2026-05-11 | Cardinals digest pipeline cleanly separated from the fantasy report's PDF + Readdle + Fly destinations. Cardinals ships to Blot only. Commit `fa1c804`. |
