# Cardinals Daily Report

A standalone Cardinals-focused intelligence report that runs alongside the fantasy report. Each morning it generates a Cardinals-only markdown, renders it as a Cardinals-themed PDF, publishes it to the Brian Renshaw Blot blog, syncs it to the Readdle iCloud folder for mobile reading, and uploads it to Fly for the web app.

This document covers the full pipeline: code layout, sources, sections, output destinations, monitoring, and recovery.

---

## At a glance

| What | When | Where |
|---|---|---|
| Cardinals report MD generated | 3 AM daily (launchd) | `data/content/analysis/{date}_cardinals-daily.md` |
| Cardinals-themed PDF rendered | 3 AM, after MD | `data/content/analysis/{date}_cardinals-daily.pdf` |
| PDF synced to mobile | 3 AM, after render | `~/Library/CloudStorage/.../Apps/Blot/Posts/` (via Dropbox) **and** `~/Library/Mobile Documents/.../Documents/Fantasy Baseball Analysis/` (Readdle / iCloud) |
| MD uploaded to web app | 3 AM, after Blot publish | Fly volume at `/data/content/analysis/` |
| Verifier checks artifacts | 4 AM daily (launchd) | `data/content/logs/verify_problems.log` + macOS notification on failure |
| Blot publishes to blog | Whenever Dropbox syncs | `https://briandrenshaw.blot.im/cardinals-daily-{date}` |

Model: `claude-opus-4-7` via the bundled `claude -p` CLI, drawing from the user's Claude Max subscription (not metered API).

---

## Pipeline flow

The 3 AM run is `scripts/daily_content_ingest.sh`, which executes these steps in order:

1. **Transcript collector** — moves new MacWhisper-finished `.txt` files into the formatted transcripts dir
2. **Blog ingest** — fetches RSS items into `data/content/blogs/` (fangraphs, pitcherlist, rotowire, viva_el_birdos, redbird_rants, cardinal_nation)
3. **Podcast download** — drops `.mp3` + `.json` sidecars into MacWhisper's `audio/pending/` (fantasy + Cardinals podcasts)
4. **Yahoo league sync** — refreshes the fantasy DB
5. **Daily Analysis (fantasy)** — `scripts/daily_analysis.py` produces the fantasy report
6. **Cardinals Daily Report** — `scripts/cardinals_daily_report.py` produces the Cardinals report
7. **PDF Export** — `md2pdf` renders both fantasy and Cardinals MDs to Cardinals-themed PDFs
8. **Sync PDFs to Readdle** — copies both PDFs into the Readdle iCloud folder for mobile reading
9. **Upload MDs to Fly** — pushes all generated markdowns to the Fly volume for the web app

The Blot publish happens inside step 6 (the Cardinals script writes to the Dropbox/Blot/Posts folder directly).

---

## Code layout

| Path | Purpose |
|---|---|
| `scripts/cardinals_daily_report.py` | The report generator. Loads content, fetches postgame data + headlines, builds the prompt, invokes Opus via `claude -p`, writes local MD, publishes to Blot. |
| `scripts/republish_to_blot.sh` | One-command recovery: re-publishes today's (or any date's) local MD to Blot **without** regenerating via Claude. Use when the 4 AM verifier flags a missing Blot post. |
| `app/services/cardinals_postgame.py` | Fetches yesterday's MLB Cardinals game data via `statsapi` + `pybaseball`. Returns boxscore, line score, Statcast highlights (hitters + pitchers), and the Baseball Savant gamefeed URL. |
| `scripts/daily_content_ingest.sh` | The 3 AM launchd wrapper. Orchestrates all daily steps. |
| `scripts/verify_daily_ingest.sh` | The 4 AM launchd verifier. Checks artifacts exist, pings a macOS notification on failure, writes status to `data/content/logs/`. |
| `scripts/blog_ingest.py` | RSS blog fetcher. `RSS_FEEDS` dict lists all configured feeds. |
| `scripts/podcast_transcriber.py` | Podcast downloader + transcriber. Downloads episodes, calls `mw transcribe` per file, writes markdown to `transcripts/`. `PODCAST_FEEDS` dict lists all sources. |
| `docs/cardinals-blot.css` | Cardinals theme stylesheet — paste into Blot dashboard → Template → `style.css`. |
| `docs/cardinals-blot-head.html` | Drop-in for Blot's `head.html` template. This blog's naming is inverted: `head.html` holds the visible site header (Lankford Legends home link + Archives / About / RSS nav). |
| `docs/cardinals-blot-header.html` | Drop-in for Blot's `header.html` template. The `<head>` metadata block: OG tags, Twitter card meta, RSS auto-discovery, Cardinals fonts preload. |
| `docs/cardinals-blot-entries.html` | Drop-in `entries.html` (homepage post index). |
| `docs/cardinals-blot-archives.html` | Drop-in `archives.html` (full archive page). |

---

## Content sources

Three independent data streams feed the report:

### 1. Cardinals-specific content (blogs + transcripts)

Loaded from the local `data/content/blogs/` and `data/content/transcripts/` folders, filtered by feed-key prefix. Defined by `CARDINALS_SOURCES` in `cardinals_daily_report.py`:

- `viva_el_birdos` — Viva El Birdos blog (SB Nation Cardinals site)
- `redbird_rants` — Redbird Rants (FanSided Cardinals site)
- `cardinal_nation` — The Cardinal Nation (often 403-blocked; ingested when feed is reachable)
- `locked_on_cardinals` — Locked On St. Louis Cardinals podcast (transcribed via MacWhisper)
- `walton_and_reis` — Wednesday With Walton and Reis (The Cardinal Nation podcast, transcribed)
- `bschaeff_daily` — B-Schaeff Daily: St. Louis Cardinals Talk, Every Day (Brenden Schaeffer, transcribed via MacWhisper)

To add a new Cardinals source: register it in `RSS_FEEDS` (blog) or `PODCAST_FEEDS` (podcast) and append the feed key to `CARDINALS_SOURCES`. Add the display name and homepage URL to `SOURCE_HOMEPAGES` and `SOURCE_NAME_TO_KEY` in `cardinals_daily_report.py` so `linkify_sources` can attach hyperlinks.

### 2. League-wide news headlines (live RSS at generation time)

`MLB_NEWS_FEEDS` — used for the "Around the League" section:

- ESPN MLB: `https://www.espn.com/espn/rss/mlb/news`
- MLB.com: `https://www.mlb.com/feeds/news/rss.xml`

Headlines from the last 24 hours, deduplicated, capped at 25 candidates. The prompt instructs the model to filter for baseball-action items (game results, transactions, injuries, suspensions, performance) and exclude human-interest, anniversaries, charity, clickbait.

### 3. Baseball analysis longreads (live RSS at generation time)

`ANALYSIS_FEEDS` — used for the "Interesting Analysis" closing section:

- FanGraphs blog
- Pitcher List
- RotoWire MLB News
- CBS Fantasy Baseball (podcast episode descriptions)
- FantasyPros Baseball (podcast)
- Locked On Fantasy Baseball (podcast)
- In This League (podcast)
- Effectively Wild (FanGraphs analytical podcast)
- FanGraphs Audio (FanGraphs podcast feed)

Headlines from the last 72 hours, deduplicated, capped at 40 candidates. The prompt instructs the model to filter STRICTLY for general baseball analysis (scouting, pitch design, advanced stats, longreads, league-wide trends) and EXCLUDE fantasy-focused items (rankings, draft, projections, waiver, start/sit, DFS) and Cardinals-specific items (they have their own section earlier).

### 4. Postgame data (MLB Stats API + Baseball Savant)

`app/services/cardinals_postgame.py:get_cardinals_postgame(target_date)` returns a structured payload:

```python
{
  "date": "2026-05-09",
  "matchup": "St. Louis Cardinals @ San Diego Padres",
  "result": "St. Louis Cardinals 2, San Diego Padres 4 (STL L)",
  "status": "Final",
  "winning_pitcher": "Randy Vásquez",
  "losing_pitcher": "Dustin May",
  "save_pitcher": "Mason Miller",
  "venue": "Petco Park",
  "away_team": "St. Louis Cardinals",
  "home_team": "San Diego Padres",
  "stl_is_home": false,
  "game_pk": 823304,
  "savant_url": "https://baseballsavant.mlb.com/gamefeed?date=2026-05-09&gamePk=823304",
  "boxscore": {
    "batters": [...],
    "pitchers": [...]
  },
  "line_score": {
    "innings": [{"num": 1, "away": {...}, "home": {...}}, ...],
    "totals": {"away": {"R": 2, "H": 7, "E": 1}, "home": {...}}
  },
  "statcast_highlights": {
    "hardest_hit": [...],         # hitter — top 3 EV
    "best_xwoba": [...],          # hitter — top 3 xwOBA on contact
    "barrels": [...],             # hitter — Statcast-classified barrels
    "top_pitches": [...],         # pitcher — top 3 velocity
    "top_whiffs": [...],          # pitcher — top 3 swinging-strike velocity
    "best_putaways": [...],       # pitcher — top 3 K-ending pitches
    "lowest_xwoba_allowed": [...] # pitcher — best contact-suppression
  }
}
```

Returns `None` on off-days (no Cardinals game on the target date). The report then drops into **off-day mode**: `get_cardinals_next_game(today)` (also in `app/services/cardinals_postgame.py`) walks forward up to 7 days for the next scheduled regular-season game and returns `{date, stl_is_home, opp_team, opp_short, venue, game_time, stl_probable_pitcher, opp_probable_pitcher}`. The Score and Data heading reads `## Score and Data for {off-day date} (off day)` (using yesterday's date, not the publish date) and the body is a fixed two-sentence lede plus a probable-starters line — no box score, no WPA, no game analysis. The fact-check loop is skipped on off days because the lede is forward-looking by design. The OG banner and Blot post title stamp the off-day date for the same reason.

**Primary source: Savant gamefeed JSON.** `_fetch_savant_gamefeed(game_pk)` pulls `https://baseballsavant.mlb.com/gf?game_pk={pk}`, which Savant populates within minutes of game end. `_highlights_from_gamefeed()` builds the same payload shape from the JSON's `team_home` / `team_away` / `exit_velocity` lists. Each event ships `pitcher_name` and `batter_name` directly — no MLBAM-id lookup needed. Statcast metric: **xBA** (gamefeed doesn't expose xwOBA on every event). Barrels are computed via an EV+launch-angle approximation (`launch_speed ≥ 98` with the standard barrel-zone angle band).

**Fallback: pybaseball.statcast_single_game**. Only invoked if the gamefeed yields no usable highlights. Earlier the primary source — kept for resilience but rarely runs now. Note: under pybaseball, `player_name` is the **batter** on every row, so pitcher highlights have to look up names via the `pitcher` MLBAM id column against the boxscore's `_build_pid_to_name()` map.

**Why the switch:** pybaseball queries the `statcast_search/csv` endpoint, which lags hours behind the gamefeed JSON for fresh games (especially Sunday games or late West Coast slots). On 5/11, the gamefeed had full Statcast for the 5/10 STL game by 3 AM while the CSV endpoint was still empty — the report shipped with "Statcast highlight detail unavailable" until we swapped to gamefeed.

---

## Report sections (current order)

The Cardinals report has **5 sections**, written in this order:

1. **Score and Data for {Month D, YYYY}** — header line with score / venue / pitchers / Savant link, line-score table, batter/pitcher box scores, Statcast highlights (hitters + pitchers), Scout Notes (3-5 scout-flavored bullets), game analysis paragraphs.
2. **Cardinals Notebook** — beat-writer prose on roster, performance, narratives, off-field. Replaces the older "MLB Cardinals" name to avoid Blot's H2 title-case mangling of all-caps acronyms.
3. **Beat Writer's Verdict** — closing analytical 2-3 paragraphs in third-person beat-writer voice.
4. **Around the League** — 5-7 linked headlines from ESPN MLB / MLB.com (game results, transactions, injuries, milestones).
5. **Interesting Analysis** — 4-6 linked longreads from FanGraphs, Effectively Wild, and other analytical baseball sources. Strictly non-fantasy and non-Cardinals.

Section instructions live in `SECTION_INSTRUCTIONS` in `cardinals_daily_report.py`. Edit there to change formatting, tone, or filters.

---

## Output destinations

### Local markdown
`data/content/analysis/{date}_cardinals-daily.md` — the canonical source. All other outputs derive from this file.

### Cardinals-themed PDF
Rendered by the user's external `~/Projects/md2pdf/` tool (Cardinals theme = red headers, navy text, yellow table accents). Saved next to the MD.

### Readdle iCloud folder (mobile)
Copy of the PDF synced to `~/Library/Mobile Documents/3L68KQB4HG~com~readdle~CommonDocuments/Documents/Fantasy Baseball Analysis/`. Propagates to phone within minutes via iCloud.

### Fly.io web app
The MD is uploaded to `/data/content/analysis/{date}_cardinals-daily.md` on the Fly volume via `flyctl ssh sftp`. The web app's Intel tab renders it.

### Blot blog
A separate Blot-formatted MD is written to `~/Library/CloudStorage/Dropbox-Brianrenshawmedia/Brian Renshaw/Apps/Blot/Posts/{date}-cardinals-daily.md`. Blot's Dropbox watcher picks it up and publishes to `https://briandrenshaw.blot.im/cardinals-daily-{date}`.

**Blot post format differences vs. the local MD**:
- Frontmatter: Blot uses its own key:value syntax (`Title:`, `Date:`, `Summary:`, `Link:`) instead of YAML.
- Title: computed from postgame data (e.g., `@ Padres 2-4 (L) — May 9`), not the literal H1 from the report.
- Summary: one-line preview (e.g., `Cardinals 2, San Diego Padres 4 at Petco Park.`) — rendered on the homepage post list.
- H1: stripped (Blot derives the page title from the metadata).
- Tags: omitted (Blot's tag iteration variable doesn't match what the template expects, so tag chips would render empty).
- Headings: ZWSP (U+200B) inserted between adjacent uppercase letters (e.g., `JJ` → `J​J`, `MLB` → `M​L​B`). This defeats Blot's server-side small-caps wrapping that mangles all-caps words in headings.

---

## Blot template files

The user maintains a "Copy of Blog" template on Blot. Five files need the Cardinals-theme content. Note: this blog's `head.html` / `header.html` naming is inverted from standard HTML convention. The repo file names follow what Blot calls them, so `cardinals-blot-head.html` contains the visible site header and `cardinals-blot-header.html` contains the `<head>` metadata.

1. **`style.css`** ← contents of [docs/cardinals-blot.css](cardinals-blot.css)
   Cardinals red/navy/yellow palette, Roboto Slab + Inter fonts, table styling, `.small-caps` override.
2. **`head.html`** ← contents of [docs/cardinals-blot-head.html](cardinals-blot-head.html)
   The visible `<header>` block. Lankford Legends home link, Archives / About / RSS nav.
3. **`header.html`** ← contents of [docs/cardinals-blot-header.html](cardinals-blot-header.html)
   The `<head>` metadata block. OG tags, Twitter card meta, RSS auto-discovery, Google Fonts preconnect.
4. **`entries.html`** ← contents of [docs/cardinals-blot-entries.html](cardinals-blot-entries.html)
   Clean magazine-style homepage: title link + one-line summary. No tag iteration (broken on this template). No body excerpt.
5. **`archives.html`** ← contents of [docs/cardinals-blot-archives.html](cardinals-blot-archives.html)
   Search input, popular-tags cloud, full list of posts with dates. This is the original Blot Blog archives template, kept verbatim aside from minor formatting.

To apply: Blot dashboard → Template → Edit code → click each file → paste contents → Save. Dropbox sync triggers a rebuild within minutes.

---

## Monitoring and recovery

### 4 AM verifier
`scripts/verify_daily_ingest.sh` runs at 4 AM via launchd (`com.fantasybaseball.verify-ingest.plist`). Checks:

- Ingest log exists and reached the final marker
- Yahoo ETL completed successfully
- Fly upload count > 0
- Local Cardinals MD exists (soft warning)
- Blot post present in the Dropbox folder (FAIL-level)
- DB updated within the last 6 hours

On failure: appends a structured entry to `data/content/logs/verify_problems.log`, writes a single-line status to `data/content/logs/last_verified.txt`, and pops a macOS notification via `osascript`.

### One-command recovery
If the verifier flags `Blot post published: FAIL` (e.g., Dropbox was paused at 3 AM), run:

```bash
./scripts/republish_to_blot.sh
```

This re-publishes the existing local MD to the Blot folder. No Claude regen, no quota burn — just a fresh write to disk. Dropbox picks it up on its next sync. For a specific date:

```bash
./scripts/republish_to_blot.sh 2026-05-10
```

### Force regenerate
If the content itself looks wrong (model produced a bad section, missed something obvious), trigger a full regen:

```bash
uv run python -m scripts.cardinals_daily_report --force
```

This re-runs Opus via `claude -p`, overwrites the local MD, re-publishes to Blot, and re-derives the title + summary from the same postgame data. Then run the PDF render + Readdle copy manually if you want the mobile PDF updated.

---

## Configuration knobs

### Environment variables
- `DAILY_ANALYSIS_USE_CLI=1` (default) — use the bundled `claude -p` binary, draws from the Max subscription. Set to `0` to use the Anthropic API with `ANTHROPIC_API_KEY`. The Cardinals report only supports the CLI path; it errors out cleanly if `DAILY_ANALYSIS_USE_CLI=0`.
- `CLAUDE_CLI_PATH=...` — override autodetected `claude` binary path. Default picks the highest-numbered VSCode extension's bundled `claude` from `~/.vscode/extensions/`.

### Script flags
- `--force` — regenerate even if today's report already exists
- `--dry-run` — print prompt assembly stats without calling Claude
- `--days N` — content-window lookback (default 5 days)
- `--date YYYY-MM-DD` — override the report date (covered game = this date minus one)
- `--skip-factcheck` — bypass the Opus 4.7 fact-check loop. Emergency / debug only; the 3 AM cron does not use this flag

### Fact-check loop
On every run the writer's Score and Data section is fed to a second Opus 4.7 call (`scripts/factcheck_cardinals.py`) that verifies every numeric and factual claim against the postgame JSON plus the Baseball Reference play-by-play cross-reference. On failure the runner loops surgical edits (sends Claude the previous draft + only the flagged phrases + an instruction to edit ONLY those phrases) up to `MAX_FACTCHECK_ATTEMPTS = 6` before quarantining to `data/content/analysis/factcheck_failed/`. See `docs/cardinals-digest-process-doc.md` for the full mechanics.

### Constants in code
- `CARDINALS_SOURCES` — feed-key allowlist for Cardinals-specific content filtering
- `MLB_NEWS_FEEDS` — RSS feeds for the Around the League section
- `ANALYSIS_FEEDS` — RSS feeds for the Interesting Analysis section
- `REPORT_SLUG` — filename suffix for the markdown output
- `CONTENT_WINDOW_DAYS` — default content lookback window
- `BLOT_POSTS_DIR` — hardcoded path to the Blot Dropbox folder

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Blot post missing despite local MD present | Dropbox app paused / signed out / unmounted | Resume Dropbox; run `./scripts/republish_to_blot.sh` |
| Pitcher highlights show batter names (e.g., "Manny Machado threw a sinker") | Boxscore fetch failed → `pid_to_name` map is empty → falls back to `player_name` (which is the batter under `statcast_single_game`) | Re-run with `--force`; check `statsapi.boxscore_data()` not raising |
| Tags render as empty chips on Blot homepage | Blot's tag iteration variable changed; the template falls through to parent context | Tags are now omitted in entries.html — confirm latest template files are pasted |
| "Mlb" or "Jj" appears in H2/H3 headings on Blot | Blot's server-side small-caps wrapping mangles all-caps words inside headings | Confirm publisher applies `_defeat_blot_heading_titlecase` (ZWSP between adjacent caps); check Blot file with `hexdump` to see `4A E2 80 8B 4A` for `JJ` |
| Cardinals section says "off day" but there was a game | Statsapi.schedule call failed or game data not yet posted | Check `data/content/logs/ingest_*.log` for postgame fetcher errors |
| Statcast highlights all show "(field_out)" with no EV, or section says "unavailable" | Savant gamefeed JSON also empty (rare — usually populated within an hour of game end). Pybaseball CSV fallback may still be empty too. | Re-run `cardinals_daily_report --force` after the gamefeed populates. As of 2026-05-11 the primary source is the Savant gamefeed JSON (`/gf?game_pk=`), so this is far less common than under the old pybaseball-only setup. |
| `claude -p` times out at 3 AM but succeeds when re-run | Cold start on scheduled wake; not a code problem | Already handled — timeout is 1800s with one retry on `TimeoutExpired` |
| Headlines in Interesting Analysis section are mostly fantasy | Filter not strict enough in this run | Tighten the EXCLUDE rules in the section instruction; or regen — the model's filtering varies run to run |

---

## What's NOT in this report

- Minor league prospect tracking (intentionally cut — low signal value vs effort)
- Live in-game updates (this is a daily morning report, not real-time)
- Trade-deadline simulation or roster proposal tools (those live in the fantasy app, not the Cardinals beat)
- Pure highlights / video clips (no media embedding; URLs only)
