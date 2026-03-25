# Developer's Playbook

A comprehensive technical guide to Lankford Legends — its architecture, data sources, algorithms, and how everything fits together.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [External Data Sources](#2-external-data-sources)
3. [Database Layer](#3-database-layer)
4. [ETL Pipeline](#4-etl-pipeline)
5. [Services Deep Dive](#5-services-deep-dive)
6. [Claude API Integration](#6-claude-api-integration)
7. [League Scoring System](#7-league-scoring-system)
8. [Frontend Architecture](#8-frontend-architecture)
9. [Caching Strategy](#9-caching-strategy)
10. [Scheduler & Automation](#10-scheduler--automation)
11. [Testing](#11-testing)
12. [Development Commands](#12-development-commands)
13. [Fly.io Deployment](#13-flyio-deployment)
14. [Backtesting Infrastructure](#14-backtesting-infrastructure)
15. [Quality Gate Process](#15-quality-gate-process)
16. [Phase 5: Self-Optimization (April 30 Hold)](#16-phase-5-self-optimization-april-30-hold)

---

## 1. Architecture Overview

### Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Backend | FastAPI | Async-native Python web framework with dependency injection |
| Templating | Jinja2 | Server-side HTML rendering; pairs with HTMX for partial updates |
| Frontend | HTMX + Tailwind CSS + Plotly.js | Minimal JS, server-driven UI, interactive charts |
| Database | SQLite via SQLAlchemy (async + aiosqlite) | Zero-config, single-file DB; async for non-blocking I/O |
| Optimization | PuLP | Integer Linear Programming for lineup optimization |
| AI | Anthropic Claude API | Tool-use chat assistant with league context |
| Scheduling | APScheduler | Automated ETL jobs (Yahoo every 6h, stats daily) |
| Caching | diskcache + pybaseball cache | TTL-based disk cache for API responses |
| Package manager | uv | Fast Python package management (always use `uv add`, not `pip install`) |

### Data Flow

```
                    ┌─────────────────┐
                    │  Yahoo Fantasy  │
                    │      API        │
                    └────────┬────────┘
                             │ (yfpy, every 6h)
                             ▼
┌──────────────┐    ┌────────────────┐    ┌──────────────┐
│  FanGraphs   │───▶│                │    │   Anthropic  │
│  (pybaseball)│    │    SQLite DB   │◀──▶│  Claude API  │
└──────────────┘    │                │    └──────────────┘
┌──────────────┐    │  players       │           │
│  Statcast    │───▶│  batting_stats │    ┌──────┴──────┐
│  (pybaseball)│    │  pitching_stats│    │  Tool-Use   │
└──────────────┘    │  statcast_sum  │    │  Loop (DB   │
┌──────────────┐    │  rosters       │    │  queries)   │
│  MLB-StatsAPI│───▶│  projections   │    └─────────────┘
│  (statsapi)  │    │  trade_values  │
└──────────────┘    │  player_points │
┌──────────────┐    └───────┬────────┘
│  Smart FFB   │────────────┘
│  ID Map CSV  │     (id crosswalk)
└──────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │   FastAPI +    │
                    │   Jinja2 +     │
                    │   HTMX         │
                    └────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │   Browser:     │
                    │   Tailwind +   │
                    │   Plotly.js    │
                    └────────────────┘
```

### Directory Structure

```
app/
├── main.py                     # FastAPI app, lifespan, scheduler, route registration
├── config.py                   # Pydantic settings from .env
├── database.py                 # SQLAlchemy engine, sessions, migrations
├── league_config.py            # H2H Points scoring rules & strategic constants
├── models/                     # SQLAlchemy ORM models (14 tables)
├── services/                   # Business logic (20+ service modules)
├── routes/                     # FastAPI route handlers (12 modules)
├── etl/                        # Extract-Transform-Load pipeline
│   ├── pipeline.py             # Orchestrator (Yahoo + Stats pipelines)
│   ├── extractors.py           # Pull from Yahoo API
│   ├── transformers.py         # Normalize & deduplicate
│   └── loaders.py              # Upsert to SQLite
├── templates/                  # Jinja2 HTML (full pages + HTMX partials)
└── static/
    ├── css/custom.css
    └── js/                     # Charts, comparison tool, tooltips
```

---

## 2. External Data Sources

### Yahoo Fantasy API (`app/services/yahoo_service.py`)

**What it provides:** League-specific data — rosters, standings, matchups, transactions, free agents, scoring categories, weekly stats.

**Why:** This is the source of truth for everything league-specific. No other API knows who's on your roster, what your scoring rules are, or who's available on waivers.

**How it works:**
- Uses the `yfpy` library, which wraps Yahoo's OAuth2-authenticated REST API
- First run triggers a browser-based OAuth flow; token auto-refreshes after that
- All sync calls run in `asyncio.run_in_executor()` to avoid blocking the event loop
- 0.5-second delay between calls to respect Yahoo's rate limits
- Lazy-loads a singleton `YahooFantasySportsQuery` instance on first use

**Key endpoints called:**
| Method | Data Retrieved |
|--------|---------------|
| `get_league_teams()` | All teams, identifies current user's team |
| `get_league_standings()` | Standings (W-L-T, points for/against) |
| `get_team_roster_player_stats()` | Roster with player stats |
| `get_league_transactions()` | Recent trades, pickups, drops |
| `get_league_players()` | Free agents list |
| `get_team_matchups()` | Current H2H matchup |
| `get_league_scoreboard_by_week()` | Weekly matchup scores |

### FanGraphs (`app/services/fangraphs_service.py`, `app/services/external_projections.py`)

**What it provides:** Two categories of data:
1. **Actual stats** — AVG, OBP, SLG, wOBA, wRC+, ISO, BABIP, FIP, xFIP, SIERA, K%, BB%, WAR, and more
2. **Consensus ROS projections** — Rest-of-season counting stat projections from Steamer, ZiPS, and ATC, blended into a consensus forecast

**Why:** FanGraphs is the gold standard for advanced baseball analytics. Their metrics (FIP, xFIP, SIERA, wRC+) are better predictors of future performance than raw stats. For projections, research shows consensus blending of multiple independent systems outperforms any single system — it was literally the #1 most accurate approach in recent accuracy studies.

**How it works — two separate methods:**

#### Method 1: pybaseball scraping (actual stats)
- `fangraphs_service.py` uses the `pybaseball` library, which scrapes FanGraphs leaderboard pages
- Under the hood, pybaseball hits FanGraphs' internal JSON endpoints and parses the responses into DataFrames
- Retry logic: 3 attempts with 5-second delays between failures
- Column name mapping normalizes FanGraphs output to our DB schema
- `qual=0` (no minimum PA/IP) to capture all rostered players

#### Method 2: FanGraphs internal JSON API (projections)
- `external_projections.py` calls `https://www.fangraphs.com/api/projections` directly using `httpx`
- This is the same endpoint that FanGraphs' own projections page calls in the browser — we mimic a browser request with User-Agent headers
- Supports multiple projection systems via the `type=` parameter: `steamer`, `zips`, `atc`
- Returns JSON with full counting stats (HR, 2B, BB, K, IP, SV, HLD, ER, etc.)
- Each system is fetched individually with a 2-second delay between calls to avoid rate limiting
- Results are blended into consensus projections (equal weight across available systems) and stored in the `projections` table with `system='consensus'`
- Steamer is also stored separately as `system='steamer_ros'` for comparison
- Matched to players via `fangraphs_id` or `mlbam_id` (the API returns `xMLBAMID`)

#### API Dependency Risk

**FanGraphs does not offer an official public API.** Both methods above use unofficial access:

| Method | Risk | Mitigation |
|--------|------|------------|
| pybaseball scraping | Page format changes can break parsing (e.g., the `320 columns passed` error seen in early-season 2026) | Retry logic, pybaseball caching, graceful fallback to consensus projections when stats fail |
| Internal JSON API | Endpoint could change or be blocked | Browser-like headers, rate limiting (2s delays), consensus degrades gracefully if one system fails |

**Context:** pybaseball has 18k+ GitHub stars and is the standard community tool for accessing FanGraphs data. FanGraphs has tolerated this access pattern for years. The internal projections API in particular has been stable and is the same API FanGraphs' own React frontend uses — it would break their own site if they changed it without a replacement. That said, this is an undocumented dependency and should be treated as one.

### Statcast / Baseball Savant (`app/services/statcast_service.py`)

**What it provides:** Expected stats (xBA, xSLG, xwOBA), exit velocity, barrel%, hard-hit%, sweet spot%, sprint speed, whiff%, chase%.

**Why:** Statcast measures what a player *should* be doing based on quality of contact, not what actually happened. A player with a .230 BA but .280 xBA is getting unlucky — that's a buy-low signal. Statcast gets 50% of our projection weight because it's the best predictor of future performance.

**How it works:**
- Also fetched via `pybaseball` (which pulls from Baseball Savant)
- Merges two datasets: expected stats (xBA/xSLG/xwOBA) + exit velocity/barrel data, joined on `mlbam_id`
- Derives `xERA` for pitchers when not directly available (estimated from xwOBA-against using league-average conversions)
- Sprint speed data fetched separately and merged into batter summaries
- Same 3-retry pattern as FanGraphs

### MLB-StatsAPI (`app/services/mlb_service.py`)

**What it provides:** Real-time MLB data — game schedules, probable pitchers, injury reports, active rosters, player ages.

**Why:** Yahoo doesn't provide MLB schedule data, probable starters, or injury details. We need these for weekly lineup optimization (who's pitching? how many games does each team play?) and for surfacing injury alerts.

**How it works:**
- Uses the `statsapi` Python library (unofficial but stable MLB Stats API wrapper)
- Injury data cached for 2 hours
- Game status parsing: "Preview" → "Live" → "Final"
- Team ID mapping handles abbreviation aliases (ARI↔AZ, CWS↔CHW, WSH↔WAS)

**Key functions:**
| Function | Returns |
|----------|---------|
| `get_probable_pitchers()` | Today's probable starters with game info |
| `get_schedule()` | Full game schedule for a date range |
| `get_injuries()` | Current MLB-wide injury report |
| `get_team_roster()` | Active roster for an MLB team |
| `get_standings()` | Current MLB standings |

### Smart Fantasy Baseball ID Map (`app/services/id_mapper.py`)

**What it provides:** A CSV mapping player IDs across platforms — Yahoo, FanGraphs, MLBAM (Statcast), Baseball Reference.

**Why:** Every data source uses different player IDs. Yahoo calls Mike Trout "10155", FanGraphs calls him "10155" (coincidence), and MLBAM calls him "545361". To combine Yahoo roster data with FanGraphs stats and Statcast metrics for the same player, we need a crosswalk.

**How it works:**
- Downloads the CSV from `https://www.smartfantasybaseball.com/PLAYERIDMAPCSV`
- Cached in memory after first load
- `seed_crosswalk()` bulk-populates missing IDs on existing Player records and creates new players from the map
- Deduplication logic prevents creating duplicate players (e.g., Ohtani appears in both batting and pitching rows)

---

## 3. Database Layer

### Engine & Sessions (`app/database.py`)

```python
engine = create_async_engine("sqlite+aiosqlite:///./fantasy_baseball.db", echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

- Fully async via `aiosqlite` — no blocking I/O on database operations
- `expire_on_commit=False` prevents lazy-load issues after commit
- `get_session()` is a FastAPI dependency that yields an `AsyncSession` and auto-closes

### Migration Strategy

Instead of Alembic, we use a lightweight idempotent migration system:

```python
_MIGRATIONS = [
    ("pitching_stats", "k_pct", "FLOAT"),
    ("pitching_stats", "bb_pct", "FLOAT"),
    ("players", "birth_date", "DATE"),
    ("players", "age", "INTEGER"),
    # ...
]
```

Each migration is an `ALTER TABLE ADD COLUMN` wrapped in a try/except. If the column already exists, the exception is silently caught. This runs on every startup via `init_db()`, making it safe and idempotent.

### Core Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `players` | Master player registry | `yahoo_id`, `fangraphs_id`, `mlbam_id`, `bbref_id`, `name`, `team`, `position` |
| `batting_stats` | Batting stats by period/source | `player_id`, `season`, `period` (full_season/last_30/last_14), `source`, 23+ stat columns |
| `pitching_stats` | Pitching stats by period/source | Same structure, 27+ stat columns including FIP, xFIP, SIERA, K-BB% |
| `statcast_summary` | Expected stats from Statcast | `player_type` (batter/pitcher), `xba`, `xslg`, `xwoba`, `barrel_pct`, `avg_exit_velo`, `xera` |
| `rosters` | Current Yahoo league rosters | `team_id`, `team_name`, `player_id`, `roster_position`, `is_my_team` |
| `league_teams` | League standings | `rank`, `wins`, `losses`, `points_for`, `points_against` |
| `player_points` | Computed fantasy points (central) | `actual_points`, `projected_ros_points`, `steamer_ros_points`, `points_per_pa`, `surplus_value`, `positional_rank` |
| `trade_values` | VORP-based trade values | `surplus_value`, `z_score_total`, `positional_rank` |
| `projections` | Projection system outputs | `system` (steamer/zips/atc/blended/steamer_ros), `stat_name`, `projected_value` |
| `player_splits` | vs LHP/RHP, home/away | `split_type`, stats per split |
| `weekly_matchup_snapshots` | H2H weekly freezes | Projected/actual points, breakdowns (JSON) |
| `conversations` | AI chat history | `session_id`, `role`, `content`, `tool_calls` (JSON) |
| `usage_logs` | Claude API token tracking | `input_tokens`, `output_tokens`, `model` |
| `sync_logs` | ETL audit trail | `status`, `pipeline_type`, `records_processed`, `error_message` |

### Relationships

All stat/projection/roster tables have a foreign key to `players.id`. The `Player` model is the central entity that ties everything together:

```
Player ──< BattingStats
       ──< PitchingStats
       ──< StatcastSummary
       ──< Projection
       ──< Roster
       ──< PlayerPoints
       ──< TradeValue
       ──< PlayerSplits
```

---

## 4. ETL Pipeline

The ETL system lives in `app/etl/` and has two independent pipelines.

### Yahoo Pipeline (`run_pipeline`)

**Trigger:** Every 6 hours via APScheduler, or manually via `POST /api/sync`

**Cooldown:** 5-minute minimum between syncs to prevent API hammering

**Retry:** 3 attempts with exponential backoff (2s, 4s, 6s)

**Phases:**

1. **Extract** (`extractors.py`):
   - Stat categories (league scoring definitions)
   - Standings (all teams' W-L-T, points for/against)
   - All rosters (every team's players with positions and stats)
   - Recent transactions (last 5 trades/pickups/drops)

2. **Transform** (`transformers.py`):
   - Flatten players across all teams, deduplicate by `yahoo_id`
   - Map roster entries to (league_id, team_id, player_id, roster_position)
   - Map stat IDs to human-readable names via the categories dictionary
   - Infer stat type (batting vs pitching) from player position

3. **Load** (`loaders.py`):
   - Upsert players by `yahoo_id` (find-or-create)
   - Replace rosters atomically (delete all → insert new, wrapped in a savepoint for rollback safety)
   - Upsert stats by unique key `(player_id, season, stat_name, source)`
   - Replace standings per league

4. **Post-sync:**
   - Update weekly matchup actuals from synced data
   - Bulk-fetch player ages from MLB-StatsAPI (batched, 50 at a time)

**Audit:** Every run creates a `SyncLog` record with start/end times, status (success/partial/failed), record counts, and error messages.

### Stats Pipeline (`run_stats_pipeline`)

**Trigger:** Daily at 5 AM ET via APScheduler, or manually via `POST /api/sync/stats`

**Phases:**

1. Seed/update player ID crosswalk (Yahoo ↔ FanGraphs ↔ MLBAM ↔ BBRef)
2. Fetch FanGraphs batting stats (full season, `qual=0`)
3. Fetch FanGraphs pitching stats (full season, `qual=0`)
4. Fetch Statcast batter summaries (xBA, xSLG, xwOBA, barrel%, exit velo)
5. Fetch Statcast pitcher summaries (xERA, whiff%, chase%)
6. Fetch sprint speed data (merged into batter records)
7. Bulk-update player ages from MLB-StatsAPI
8. Fetch consensus ROS projections from FanGraphs API — Steamer, ZiPS, and ATC fetched individually, blended with equal weights, stored as `system='consensus'` in projections table. Steamer also stored separately as `system='steamer_ros'` for comparison.
9. Calculate player points from consensus projections (primary) with Steamer ROS attached for comparison. Early season: when no actual stats exist, PlayerPoints are populated entirely from consensus projections.

**Loading patterns:**
- Match players by `fangraphs_id` or `mlbam_id`
- Upsert by `(player_id, season, period, source)`
- `_safe_val()` filters out NaN/inf values to prevent database corruption

---

## 5. Services Deep Dive

### Projection Engine — Unified Consensus Architecture

The projection engine uses a **consensus blending** approach: professional projection systems (Steamer, ZiPS, ATC) are fetched from FanGraphs and blended with equal weights to produce a single consensus projection. This consensus is the single source of truth for all downstream features.

**Why consensus?** Backtesting (see `docs/BACKTESTING_METHODOLOGY.md`, Section 8.6) demonstrated that custom blending from season-level stats cannot beat the Marcel baseline. Professional systems use proprietary multi-year regression, aging curves, and park adjustments that are impractical to replicate. Research consistently shows that averaging multiple independent projection systems outperforms any single system. The app's value-add is in league-specific scoring conversion and matchup adjustments, not raw stat projection.

**Consensus Pipeline (`app/services/external_projections.py`):**
1. Fetch Steamer, ZiPS, and ATC ROS projections from FanGraphs API
2. Blend with equal weights (1/3 each) across all counting and rate stats
3. Store in the `Projection` table with `system="consensus"`
4. Each source system is also stored individually (`system="steamer_ros"`, etc.) for comparison

**What consensus provides:**
- ROS counting stats (HR, R, RBI, SB, IP, K, SV, etc.)
- ROS rate stats (AVG, OBP, SLG, ERA, WHIP, etc.)
- Per-PA and per-IP rates derived from consensus counting stats

**Points conversion (`app/services/points_service.py`):**
- `PlayerPoints.projected_ros_points` derives from consensus counting stats scored with league weights
- Rate stats (`points_per_pa`, `points_per_ip`) calculated from consensus, not pace-scaling
- Fallback: if consensus is unavailable for a player, falls back to pace-based projection from actual stats

**Buy/sell signals (still active):**
- Buy low: xwOBA exceeds actual wOBA by ≥ 0.030 (player is unlucky, regression coming)
- Sell high: actual wOBA exceeds xwOBA by ≥ 0.030 (player is lucky, regression coming)

### Unified Projection Flow

All features derive from the same consensus base. This eliminates inconsistencies where the trade analyzer and weekly optimizer could disagree about a player's value.

```
Steamer + ZiPS + ATC → Consensus → PlayerPoints.projected_ros_points
     (equal weights)    (system=       (league scoring applied)
                        "consensus")          │
                   ┌──────────────────────────┼───────────────────────────┐
                   │                          │                           │
                   ▼                          ▼                           ▼
             Trade Analyzer           Weekly Optimizer               Waivers
             (surplus_value =         (consensus rates ×         (projected_score
              projected_pts -          schedule games ×           from consensus,
              replacement)             matchup quality)           trend-adjusted)
```

**How each feature uses consensus:**
- **Trade Analyzer:** `surplus_value` = consensus `projected_ros_points` minus replacement-level points at position
- **Weekly Optimizer:** Base per-game rates from consensus, then multiplied by team game count and adjusted for matchup quality (opponent pitcher ERA, park factors)
- **Waiver Wire:** Consensus `projected_score` as the primary value signal (35% weight), with trend and positional need overlaid

### Trade Analyzer (`app/services/trade_service.py`)

**Primary mode: H2H Points surplus value**

Surplus value = a player's projected ROS fantasy points minus the replacement-level player's points at that position.

Replacement level is defined as the Nth-ranked player at each position, where N = roster slots × number of teams:

| Position | Replacement Level (Nth player) |
|----------|-------------------------------|
| C | 10th |
| 1B, 2B, 3B, SS | 10th |
| OF | 30th (3 slots × 10 teams) |
| SP | 20th |
| RP | 20th |

**Trade evaluation:**
1. Sum surplus values for each side
2. Calculate the differential
3. Apply fairness thresholds:
   - Fair: |diff| < 20 points
   - Slightly favors one side: 20–75 point gap
   - Heavily favors one side: > 75 point gap

**League-specific insights the trade analyzer generates:**
- Reliever premium (SV=7, HLD=4 are outsized values)
- Starter volume value (IP=4.5 pts, innings-eaters are premium)
- Points differential translated to real-world context ("this gap equals ~3 saves")

**Triple projection display:** The trade rankings table shows three projection columns:
- **Consensus Projected** — Blended Steamer/ZiPS/ATC projection converted to league scoring (see Projection Engine)
- **Steamer ROS** — FanGraphs Steamer projections alone, converted to league scoring
- **Actual Points** — What the player has scored this season

Disagreements between Consensus and Actual highlight buy-low/sell-high opportunities (Statcast xwOBA delta signals).

**AI Trade Suggestions** (`suggest_trades_ai()`):
- Scans ALL opponent rosters against user's roster
- Identifies roster weak spots (positions <70% of roster average)
- Gathers injuries, Statcast trends (xwOBA delta last 14 vs season), projection disagreements
- Passes all context to Claude with three-tier output: aggressive move, conservative move, watch list
- Can recommend "STAND PAT" if no trade improves the team
- Max tokens: 2000

**AI Trade Analysis** (`analyze_trade_ai()`):
- Enriches a specific proposed trade's mathematical evaluation with narrative context
- Includes all three projections for traded players, roster fit, injuries, Statcast trends
- Claude leads with a verdict and explains projection disagreements
- Max tokens: 1500

**Legacy mode: 5×5 Roto Z-Score**

Calculates z-scores across 5 hitting categories (HR, R, RBI, SB, AVG) and 5 pitching categories (W, SV, K, ERA, WHIP). Inverts z-scores for lower-is-better stats (ERA, WHIP). Tighter fairness thresholds (0.5 / 2.0 z-score).

### Lineup Optimizer (`app/services/optimizer_service.py`)

Uses PuLP Integer Linear Programming to solve the optimal roster assignment.

**Formulation:**

- **Decision variables:** Binary (0/1) — `x[player][slot]` = 1 if player is assigned to slot
- **Objective:** Maximize Σ(projected_points[player] × x[player][slot])
- **Constraints:**
  1. Each player assigned to at most 1 slot
  2. Each slot filled by exactly 1 eligible player
  3. Position eligibility: a player can only fill slots matching their eligible positions

**Position eligibility map:**

```python
SLOT_ELIGIBILITY = {
    "C":    ["C"],
    "1B":   ["1B"],
    "2B":   ["2B"],
    "3B":   ["3B"],
    "SS":   ["SS"],
    "OF":   ["OF", "LF", "CF", "RF"],
    "Util": ["C", "1B", "2B", "3B", "SS", "OF", "LF", "CF", "RF", "DH"],
    "SP":   ["SP"],
    "RP":   ["RP"],
    "P":    ["SP", "RP"],   # Flexible — key strategic lever
}
```

**Slot expansion:** Multi-slot positions (e.g., OF: 3) expand to OF_1, OF_2, OF_3 for the solver.

**Points source priority:**
1. `PlayerPoints` table (`projected_ros_points`)
2. Fallback: `Projection` table with heuristic conversion to points

**Output:** `OptimizedLineup` with player→slot assignments, total projected points, and improvement over current lineup.

### Waiver Wire Scorer (`app/services/waiver_service.py`)

Scores free agents on a 0–100 composite scale. **Only unrostered players** are shown — the `_get_all_players()` function queries the `Roster` table and excludes any player on a fantasy team. Uses 5 weighted factors:

| Factor | Weight | What It Measures |
|--------|--------|-----------------|
| Projected fantasy points | 35% | Raw projected value |
| Recent trend | 25% | Last-14 Statcast vs full-season (hot/cold detection) |
| Positional need | 15% | Scarcity at the player's position |
| League scoring fit | 15% | How well the player's profile fits H2H Points scoring |
| Schedule volume | 10% | Team games remaining in period |

**Two modes:**

1. **ROS mode** (`score_free_agents`): Uses consensus projections (Steamer+ZiPS+ATC blend) when available, falls back to pace-based app projection. Both displayed as dual columns (Consensus + Steamer) in the waiver table.
2. **Weekly mode** (`score_free_agents_weekly`): Matchup-aware projections with:
   - Two-start pitcher detection
   - Team game count weighting
   - Reliever opportunity scoring (closer vacancy, save opportunities)
   - Opponent quality adjustment
   - Statcast breakout detection

**Scoring fit bonuses for this league:**
- High-K relievers (strong K rate → more points per appearance)
- Low-K contact hitters (avoid the -0.5 K penalty)
- Innings-eating starters (durability > ERA)
- High-save-opportunity closers (SV=7 is massive)

**Season fallback:** Both modes call `_best_stats_season()` which checks what seasons have data and falls back to the most recent (e.g., uses 2025 data when 2026 hasn't started). On Mondays, the weekly dropdown shifts forward (shows next week + following week instead of current + next).

**Two-way player handling:** `_compute_trend()` accepts `player_type` and filters `StatcastSummary` by `player_type` column (`"batter"` or `"pitcher"`) to avoid duplicate row errors for players with both batting and pitching statcast entries.

**AI analysis:** After scoring, the top recommendations feed into a Claude prompt that generates a narrative explanation with league-specific context, injury alerts, and trend analysis.

### Weekly Lineup Service (`app/services/weekly_lineup_service.py`)

Combines the optimizer, schedule data, and AI to produce a comprehensive weekly lineup plan.

**Workflow:**
1. Get week boundaries (Monday–Sunday)
2. Fetch team game counts for the week from schedule service
3. Get probable starters from MLB-StatsAPI
4. Fetch injury data
5. Compute weekly projections: consensus base rates (points per game from `PlayerPoints`) × team game count, then adjusted for matchup quality (opponent pitcher ERA, park factors)
6. Run the PuLP optimizer with weekly points
7. Detect two-start pitchers and injuries
8. Build swap suggestions (which bench player to start, expected point gain)
9. Get P-slot strategy recommendation (fill with SP or RP this week?)
10. Generate AI narrative with START/SIT recommendations

**AI Weekly Outlook:** A professional-voice column (ESPN/Athletic style) covering:
- H2H matchup storyline with dual projections (Yahoo vs app-calculated, with analysis of discrepancies)
- Key players to watch — every player mention includes fantasy team abbreviation, e.g. `(Empire)`, `(Ithilien)`, `(FA)`
- Schedule/weather factors
- Injury concerns
- League standings context
- Cardinals Corner (STL players on my team, opponent, and Ithilien rosters)
- Ithilien Watch (brother's team tracking)

**AI content rendering:** All AI-generated content (weekly outlook, waiver analysis, lineup analysis, Intel reports, chat) renders via Marked.js client-side markdown. The `markdown-actions.js` script also processes `[[toc]]` markers into clickable table-of-contents widgets. Copy and Email buttons on analysis partials copy rich HTML to clipboard / open mailto with subject pre-filled.

### Content Intelligence Pipeline (`scripts/`)

Automated pipeline that ingests expert fantasy baseball content and generates AI analysis reports:

- **`blog_ingest.py`** — RSS feed fetcher (FanGraphs, Pitcher List, RotoWire). Saves markdown with YAML frontmatter to `data/content/blogs/`.
- **`podcast_transcriber.py`** — Downloads podcast audio (CBS, FantasyPros, Locked On, In This League) to MacWhisper watch folder with JSON metadata sidecars.
- **`transcript_collector.py`** — Filesystem watcher (via `watchdog`) that auto-collects MacWhisper `.txt` output, wraps in markdown, saves to `data/content/transcripts/`. Runs as launchd daemon.
- **`daily_analysis.py`** — Reads content + league data from SQLite, sends to Claude Opus API in a single call, splits response into section files with per-section player/source linking. Supports daily (3 sections), Monday (+ recap), and weekly (10 sections) modes.
- **`daily_content_ingest.sh`** — Wrapper script run by launchd at 3 AM: collects transcripts → fetches blogs → downloads podcasts → generates analysis.

**Intel tab** (`app/routes/intel.py`) — Renders analysis reports in the web app with date-grouped sidebar, HTMX partial loading, and refresh button. See `docs/INTEL_PIPELINE.md` for full architecture documentation.

### Points Service (`app/services/points_service.py`)

Applies the league scoring rules to raw stats:

```python
# Batter example
points = (R * 1) + (1B * 1) + (2B * 2) + (3B * 3) + (HR * 4) + (RBI * 1)
       + (SB * 2) + (CS * -1) + (BB * 1) + (HBP * 1) + (K * -0.5)

# Pitcher example (per start)
points = (OUT * 1.5) + (K * 0.5) + (SV * 7) + (HLD * 4) + (RW * 4) + (QS * 2)
       + (H * -0.75) + (ER * -4) + (BB * -0.75) + (HBP * -0.75)
```

Handles IP → outs conversion (5.1 IP = 16 outs, not 5.1 × 3).

**ROS projection methods:**

| Method | Function | How It Works |
|--------|----------|-------------|
| **Consensus Projection** | `_build_consensus_points_map()` | Reads consensus projections from `projections` table (`system="consensus"`), groups counting stats by player, runs through `calculate_batter_points()` / `calculate_pitcher_points()`. This is the primary source for `player_points.projected_ros_points`. |
| **Steamer ROS** | `_build_steamer_points_map()` | Reads Steamer projections from `projections` table (`system='steamer_ros'`), groups counting stats by player, runs through the same scoring functions. Stored on `player_points.steamer_ros_points` for comparison. |
| **Pace-Based Fallback** | `project_batter_ros_points()` / `project_pitcher_ros_points()` | Only used when consensus is unavailable for a player. Scales actual counting stats proportionally to remaining games, scored with league weights. During offseason (< 30 games remaining), projects a full 162-game season from prior year rates. |

The consensus projection is the default for all features. The waiver wire shows both Consensus and Steamer columns. The weekly dashboard uses consensus base rates with matchup adjustments layered on top.

### Schedule Service (`app/services/schedule_service.py`)

**Batch fetching:** Single MLB-StatsAPI call for an entire date range, filtered to regular season games only.

**Key functions:**
- `get_week_boundaries()` → (Monday, Sunday) for current or future week
- `get_all_team_games_in_range()` → `{team_abbrev: game_count}` for the week
- `get_probable_starters_in_range()` → `{mlbam_id: num_starts}` for two-start pitcher detection
- `get_game_details_in_range()` → venue, weather, temperature for weekly outlook

**Team abbreviation handling:** Normalizes aliases (ARI↔AZ, CWS↔CHW, WSH↔WAS).

**Cache:** 4-hour TTL via diskcache.

### ID Mapper (`app/services/id_mapper.py`)

The glue that makes multi-source data work. Every player lookup goes through this service.

**ID systems:**
| Platform | ID Field | Example (Mike Trout) |
|----------|----------|---------------------|
| Yahoo Fantasy | `yahoo_id` | League-specific |
| FanGraphs | `fangraphs_id` | Numeric |
| MLBAM/Statcast | `mlbam_id` | 545361 |
| Baseball Reference | `bbref_id` | troutmi01 |

**`seed_crosswalk()`** is the bulk operation that runs at the start of every stats pipeline sync. It:
1. Downloads the Smart Fantasy Baseball CSV
2. Iterates all players in the map
3. For existing players (matched by yahoo_id), fills in missing IDs
4. For new players (with mlbam_id and non-FA team), creates Player records
5. Deduplication: tracks seen IDs to prevent duplicates (e.g., Ohtani appears in both batting and pitching rows)

---

## 6. Claude API Integration

### Architecture

The AI assistant uses Anthropic's tool-use API in an iterative loop. The implementation lives in two files:

- `app/services/assistant.py` — Orchestration: system prompt, API calls, tool dispatch loop
- `app/services/assistant_tools.py` — Tool definitions and handler functions

### How the Tool-Use Loop Works

```
User message
     │
     ▼
┌─────────────────────┐
│  Build messages:     │
│  system prompt +     │
│  last 20 messages +  │◀──────────────────┐
│  user input          │                   │
└──────────┬──────────┘                   │
           │                               │
           ▼                               │
┌─────────────────────┐                   │
│  Call Claude API     │                   │
│  (with tool defs)    │                   │
└──────────┬──────────┘                   │
           │                               │
           ▼                               │
     ┌───────────┐     Yes    ┌──────────────────┐
     │ Tool call? │──────────▶│ Execute tool      │
     └─────┬─────┘           │ handler (DB query) │
           │ No              └──────────┬─────────┘
           ▼                            │
┌─────────────────────┐                │
│  Return text         │    (append tool result to messages,
│  response to user    │     loop back — max 5 iterations)
└─────────────────────┘
```

**Max iterations:** 5 tool calls per user message (prevents runaway loops).

### System Prompt

The system prompt (`assistant.py:22-81`) injects full league scoring context so Claude understands the strategic implications of every recommendation:

- Reliever values (SV=7, HLD=4)
- Innings as points (IP=4.5)
- ER devastation (-4 per ER)
- K penalty (-0.5 for batters)
- Walk value (+1 free point)
- P-slot flexibility strategy
- Keeper league long-term value considerations

It also enforces rules: always use tools before answering, cite specific stats, show points math, be concise, note uncertainty.

### Available Tools (11)

| Tool | What It Queries | Use Case |
|------|----------------|----------|
| `get_player_stats` | BattingStats/PitchingStats + StatcastSummary | "How is Soto doing?" |
| `get_player_projection` | Projection engine output + buy/sell signals | "What's Soto's ROS projection?" |
| `get_position_rankings` | PlayerPoints ranked by position | "Who are the top 1B?" |
| `get_matchup_info` | Schedule + probable pitchers + stacks | "Who should I stream today?" |
| `get_head_to_head` | Batter vs pitcher context | "How does Soto hit against Wheeler?" |
| `compare_players` | Side-by-side stats + projections (2-5 players) | "Compare Soto and Judge" |
| `get_waiver_recommendations` | Waiver scorer output | "Who should I pick up?" |
| `get_team_schedule` | MLB schedule for a team | "When do the Cardinals play?" |
| `evaluate_trade` | Trade service surplus value analysis | "Should I trade Soto for Ohtani?" |
| `get_player_points` | PlayerPoints breakdown | "How many points has Soto scored?" |
| `get_scoring_config` | LEAGUE_CONFIG dictionary | "What are the scoring rules?" |

Each tool maps to an async handler function that queries the database and returns structured data for Claude to interpret.

### Token Management

- **Daily budget:** 500,000 tokens (configurable via `assistant_daily_token_limit`)
- **Usage tracking:** Every API call logs input + output tokens to the `UsageLog` table
- **Budget check:** Before each call, sums today's usage and rejects if over budget
- **Conversation history:** Last 20 messages (10 user-assistant turns) loaded from `Conversation` table to maintain context

### AI-Powered Features Beyond Chat

The Claude API is used in 6 places, not just the chat assistant:

1. **Chat assistant** (`assistant.py`) — Interactive Q&A with tool use
2. **Waiver analysis** (`waiver_service.py`) — Narrative explanation of top waiver recommendations
3. **Weekly lineup analysis** (`weekly_lineup_service.py`) — START/SIT recommendations with reasoning
4. **Weekly outlook** (`weekly_lineup_service.py`) — Comprehensive weekly column with matchup storyline, injury concerns, and personalized sections
5. **Trade suggestions** (`trade_service.py`) — Scans all opponents' rosters and suggests realistic trade packages (aggressive/conservative/watch list) using three projection systems
6. **Trade analysis** (`trade_service.py`) — Narrative analysis of a specific proposed trade with roster fit, projection disagreements, and Statcast trends

### Model Configuration

```python
assistant_model: str = "claude-sonnet-4-20250514"
assistant_max_tokens: int = 1024
```

The model is configurable via the `ASSISTANT_MODEL` environment variable. Claude Sonnet 4 is used by default for its balance of speed, cost, and quality.

---

## 7. League Scoring System

All defined in `app/league_config.py`. This is a **10-team Yahoo H2H Points keeper league** called "Galactic Empire."

### Batting Scoring

| Category | Points | Strategic Implication |
|----------|--------|---------------------|
| Runs (R) | +1 | Leadoff/high-OBP hitters get bonus value |
| Singles (1B) | +1 | Contact matters — every hit is a point |
| Doubles (2B) | +2 | Gap power has extra value |
| Triples (3B) | +3 | Speed + gap power |
| Home Runs (HR) | +4 | Still premium, but not as dominant as Roto |
| RBI | +1 | Run producers valued |
| Stolen Bases (SB) | +2 | Efficiently priced at 33% break-even |
| Caught Stealing (CS) | -1 | Minimal penalty for aggressive baserunning |
| Walks (BB) | +1 | **Free points** — high-OBP hitters undervalued |
| Hit By Pitch (HBP) | +1 | Same as a walk |
| Strikeouts (K) | -0.5 | **Contact hitters have an edge** — 75 extra Ks = 37.5 pts lost |

### Pitching Scoring

| Category | Points | Strategic Implication |
|----------|--------|---------------------|
| Each Out (OUT) | +1.5 | **IP = 4.5 pts** — innings are gold |
| Strikeouts (K) | +0.5 | Nice bonus, but outs matter more |
| Saves (SV) | +7 | **Premium** — elite closers are top assets |
| Holds (HLD) | +4 | Setup men have real value |
| Relief Wins (RW) | +4 | High-leverage relievers rewarded |
| Quality Starts (QS) | +2 | Bonus for going 6+ IP with ≤3 ER |
| Hits Allowed (H) | -0.75 | Moderate penalty |
| Earned Runs (ER) | -4 | **Devastating** — 5 ER = -20 pts |
| Walks Issued (BB) | -0.75 | Control matters |
| Hit Batters (HBP) | -0.75 | Same as a walk allowed |

### Strategic Constants (Used Throughout the App)

```python
ELITE_CLOSER_SAVE_POINTS = 12.5    # Clean 1 IP, 2K, save
POINTS_PER_INNING = 4.5            # 3 outs × 1.5
ER_PENALTY = -4.0                  # Each earned run
K_PENALTY = -0.5                   # Each batter strikeout
HR_TO_K_BREAKEVEN_RATIO = 8        # 1 HR offsets 8 extra Ks
SB_BREAKEVEN_PCT = 0.333           # Break-even steal success rate
P_SLOT_COUNT = 4                   # Flexible SP/RP slots
```

### Roster Structure

9 active hitters (C, 1B, 2B, 3B, SS, 3×OF, Util) + 8 active pitchers (2×SP, 2×RP, 4×P flex) + 4 bench + 3 IL + 1 NA.

The **4 flexible P slots** are a key strategic lever — they can be SP or RP. The weekly lineup service recommends optimal allocation based on matchup context.

---

## 8. Frontend Architecture

### HTMX Pattern

The app uses a server-driven UI pattern: HTML is rendered server-side by Jinja2, and HTMX handles partial page updates without full reloads.

**How it works:**
1. User clicks a button or submits a form
2. HTMX sends an async request (GET/POST) to a FastAPI route
3. The route returns an HTML fragment (a Jinja2 "partial" template)
4. HTMX swaps the fragment into the DOM

**Example:**
```html
<!-- Trigger a sync and replace the #sync-result div with the response -->
<button hx-post="/api/sync" hx-target="#sync-result" hx-swap="innerHTML">
    Sync Yahoo Data
</button>
<div id="sync-result"></div>
```

The route at `/api/sync` runs the ETL pipeline and returns a `partials/sync_result.html` fragment.

### Tailwind CSS

Dark theme using Tailwind's utility classes via CDN (`tailwind 3.4.17`). The base layout (`base.html`) sets `bg-gray-900 text-gray-100` on the body. No custom build step — all Tailwind classes are used directly in templates.

### Plotly.js Charts

Interactive charts render client-side from JSON data endpoints:

1. A FastAPI route at `/api/charts/*` returns JSON (x/y data, labels, colors)
2. `app/static/js/charts.js` calls Plotly with the data
3. Chart types: scatter, bar, histogram, radar

**Theme:** Dark gray plot backgrounds, Viridis colorscales. Player markers are styled by roster status:
- Stars = my team
- Circles = rostered by others
- X marks = free agents

### Key JavaScript Modules

| File | Purpose | Size |
|------|---------|------|
| `charts.js` | Plotly chart builders (scatter, bar, histogram, radar) | ~10 KB |
| `comparison.js` | Player comparison tool — drag-and-drop, percentile bars, radar, trend charts, URL sync, LocalStorage persistence | ~35 KB |
| `tooltips.js` | Info tooltip system, stat explanations, advanced analytics hover content | ~49 KB |
| `markdown-actions.js` | Markdown rendering for all AI content (via Marked.js), copy-as-rich-text to clipboard, email via mailto | ~3 KB |

### CDN Dependencies

Loaded in `base.html`:
- Tailwind CSS 3.4.17
- HTMX 2.0.4
- Plotly.js 3.0.1
- Marked.js (markdown parsing for chat)

---

## 9. Caching Strategy

### Disk Cache (`app/cache.py`)

Uses the `diskcache` library with decorator-based caching:

| Cache Scope | TTL | Why |
|-------------|-----|-----|
| Yahoo API responses | 15 minutes | League data changes slowly; avoid rate limits |
| Stats (FanGraphs, Statcast) | 24 hours | Updated daily; no need for more frequent refreshes |
| Projections | 7 days | Projection systems update weekly at most |

### pybaseball Cache

`pybaseball.cache.enable()` is called at import time. This caches FanGraphs and Statcast HTTP responses to disk, preventing redundant scraping.

### Service-Level Caches

| Service | Cache | TTL |
|---------|-------|-----|
| MLB injuries | In-memory dict | 2 hours |
| Schedule service | diskcache | 4 hours |
| Yahoo singleton | In-memory | App lifetime |
| ID mapper CSV | In-memory DataFrame | App lifetime |

---

## 10. Scheduler & Automation

APScheduler (`AsyncIOScheduler`) runs in the FastAPI lifespan:

```python
# Yahoo league sync: every 6 hours
scheduler.add_job(_job_yahoo_sync, CronTrigger(hour="*/6"))

# FanGraphs + Statcast stats: daily at 5 AM ET
scheduler.add_job(_job_stats_sync, CronTrigger(hour=5, timezone="US/Eastern"))
```

**Why these intervals?**
- Yahoo every 6h: rosters change via waivers/trades; standings update after games
- Stats daily at 5 AM: games end by ~1 AM ET; stats are finalized overnight

Both jobs are also available as manual triggers via the API:
- `POST /api/sync` — runs Yahoo pipeline
- `POST /api/sync/stats` — runs stats pipeline

---

## 11. Testing

Tests live in `tests/` and use `pytest` with `pytest-asyncio` for async support.

### Test Files

| File | What It Tests |
|------|--------------|
| `test_scoring.py` | Fantasy points calculations against known stat lines (~12 KB, comprehensive) |
| `test_optimizer.py` | PuLP lineup optimizer correctness |
| `test_trade_values.py` | Trade value and surplus value calculations |
| `test_waiver_scorer.py` | Waiver composite scoring |
| `test_projections.py` | Projection blending logic |
| `test_assistant.py` | Claude API chat tool handling |
| `test_api.py` | Route/endpoint tests |
| `test_comparison_api.py` | Player comparison endpoint tests |

### Running Tests

```bash
uv run pytest                    # Run all tests
uv run pytest tests/test_scoring.py  # Run specific test file
uv run pytest -v                 # Verbose output
```

---

## 12. Development Commands

```bash
# Start the dev server (auto-reload on file changes)
uv run uvicorn app.main:app --reload --port 8000

# Run ETL pipelines manually
uv run python -m app.etl.pipeline

# Lint
uv run ruff check .

# Format
uv run ruff format .

# Run tests
uv run pytest

# Add a dependency (NEVER use pip install)
uv add <package-name>

# Add a dev dependency
uv add --dev <package-name>

# --- Backtesting scripts ---

# Run historical data pipeline (downloads 2015-2025 data)
uv run python -m scripts.data_pipeline

# Run single season
uv run python -m scripts.data_pipeline --season 2024

# Re-download cached data (force refresh)
uv run python -m scripts.data_pipeline --force

# Run backtesting harness
uv run python -m scripts.backtest_harness

# Run backtesting for specific seasons
uv run python -m scripts.backtest_harness --seasons 2021-2024

# Run analysis scripts (output Excel files to analysis/)
uv run python -m scripts.analysis.analyze_dampening
uv run python -m scripts.analysis.analyze_park_factors
uv run python -m scripts.analysis.analyze_xwoba_regression
uv run python -m scripts.analysis.analyze_platoon_replacement
uv run python -m scripts.analysis.analyze_dynamic_weights

# Run parameter optimization (validation mode)
uv run python -m scripts.optimize_parameters --mode validation

# Run parameter optimization for specific seasons
uv run python -m scripts.optimize_parameters --mode validation --seasons 2024,2025
```

### Environment Variables (`.env`)

```
YAHOO_CLIENT_ID=your_client_id
YAHOO_CLIENT_SECRET=your_client_secret
YAHOO_LEAGUE_ID=your_league_id
YAHOO_GAME_KEY=mlb
DATABASE_URL=sqlite+aiosqlite:///./fantasy_baseball.db
ANTHROPIC_API_KEY=your_api_key
ASSISTANT_MODEL=claude-sonnet-4-20250514     # Optional override
```

### Startup Flow

1. `uvicorn` starts the FastAPI app
2. `lifespan()` context manager fires
3. `init_db()` creates all tables and runs migrations (idempotent)
4. APScheduler starts with Yahoo (6h) and stats (daily 5 AM) jobs
5. 12 route modules are registered
6. Static files mounted at `/static`
7. App is ready at `http://localhost:8000`

### Key URLs

| URL | Page |
|-----|------|
| `/` | Main dashboard |
| `/roster` | My team roster + optimizer |
| `/trades` | Trade analyzer |
| `/waivers` | Waiver recommendations |
| `/projections` | Projection explorer |
| `/stats` | Stats dashboard with Plotly charts |
| `/compare` | Player comparison tool |
| `/matchups` | H2H matchup analysis |
| `/league` | League standings dashboard |
| `/chat` | AI chat assistant |
| `/player/{id}` | Player profile page |

---

## 13. Fly.io Deployment

- **URL**: https://fantasy-baseball-br.fly.dev/
- **Config**: fly.toml with persistent volume at /data
- **Env vars**: DATABASE_URL, CACHE_DIR, DATA_DIR, CONTENT_DIR, HEADLESS, CORS_ORIGINS
- **Secrets**: YAHOO_CLIENT_ID, YAHOO_CLIENT_SECRET, YAHOO_LEAGUE_ID, ANTHROPIC_API_KEY, AUTH_PASSWORD, YAHOO_ACCESS_TOKEN_JSON
- **Health check**: GET /health every 30s
- **Deploy**: `flyctl deploy` from project root

---

## 14. Backtesting Infrastructure

The backtesting system is a standalone suite of scripts in `scripts/` that validates the projection engine against historical outcomes. All scripts read from `backtest_data.sqlite` (separate from the production `fantasy_baseball.db`) and are designed to run independently of the web application.

### Directory Structure

```
scripts/
├── __init__.py
├── data_pipeline.py           # Historical data downloader
├── backtest_harness.py        # Walk-forward projection testing
├── optimize_parameters.py     # Automated parameter tuning (scipy)
└── analysis/
    ├── __init__.py
    ├── analyze_dampening.py       # Opposing pitcher quality adjustments
    ├── analyze_park_factors.py    # Park factor strength multipliers
    ├── analyze_xwoba_regression.py # xwOBA vs wOBA predictive power
    ├── analyze_platoon_replacement.py # Platoon vs pitcher-quality adjustments
    └── analyze_dynamic_weights.py # Optimal blend weights by PA checkpoint
```

### Data Pipeline (`scripts/data_pipeline.py`)

Downloads 11 years of historical baseball data (2015–2025) from pybaseball and the Chadwick Bureau, storing everything in `backtest_data.sqlite`.

**What it downloads:**

| Data Source | Table Created | Key Columns |
|-------------|--------------|-------------|
| FanGraphs batting leaderboards | `batting_season` | `fangraphs_id`, `season`, PA, AB, H, HR, R, RBI, SB, BB, SO, AVG, OBP, SLG, wOBA, wRC+, ISO, BABIP, K%, BB%, WAR |
| FanGraphs pitching leaderboards | `pitching_season` | `fangraphs_id`, `season`, W, L, SV, HLD, IP, ERA, WHIP, FIP, xFIP, SIERA, K%, BB%, K-BB%, WAR |
| Statcast expected stats | `statcast_season` | `mlbam_id`, `season`, xBA, xSLG, xwOBA, barrel%, hard_hit%, avg_exit_velo, sprint_speed |
| FanGraphs park factors | `park_factors` | `team`, `season`, HR factor, basic factor, SO, BB, H, doubles, triples |
| Chadwick Bureau player IDs | `player_ids` | `fangraphs_id`, `mlbam_id`, `bbref_id`, `retro_id`, name fields |

**Caching:** Raw downloads are saved to `data/raw/` as CSV/Parquet files. Subsequent runs skip downloads for seasons that already have cached files unless `--force` is passed.

**Retry logic:** 3 attempts per download with 5-second delays between failures (same pattern as the production stats pipeline).

**CLI flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--season` | All (2015–2025) | Download a single season only |
| `--force` | Off | Re-download even if cached files exist |

**Statcast note:** Statcast data starts from 2016 (2015 data is sparse and excluded by default).

### Backtest Harness (`scripts/backtest_harness.py`)

Walk-forward backtesting that evaluates 4 projection methods at 3 season checkpoints across 7 test seasons (2019–2025).

**Walk-forward methodology:** For each test season T, the harness uses only data from seasons prior to T to build projections. It never looks ahead — the same constraint the production engine faces during the season. This prevents overfitting to future data.

**Projection methods tested:**

| Method | How It Projects |
|--------|----------------|
| **Current Model** | The app's production projection engine — blends traditional stats (50%) with Statcast expected stats (50%) using the 5-component weight system (full season 25%, last-30 15%, last-14 10%, full Statcast 30%, last-30 Statcast 20%) |
| **Marcel** | Bill James' Marcel method — weights prior seasons (year-1 at 5x, year-2 at 4x, year-3 at 3x) then regresses toward league average with 1200 PA denominator |
| **Naive (Last Year)** | Uses the player's most recent full-season stats with no adjustment — the simplest possible baseline |
| **League Average** | Projects every player at the league-average rate for each stat — the "no information" baseline |

**Season checkpoints:**

| Checkpoint | Hitter PA | Pitcher IP | Simulates |
|------------|-----------|------------|-----------|
| `may15` | 200 PA | 50 IP | Early-season (small sample) |
| `jul01` | 350 PA | 100 IP | Mid-season (moderate data) |
| `aug15` | 450 PA | 140 IP | Late-season (large sample) |

At each checkpoint, the harness simulates having only partial-season data by truncating player stats to the checkpoint PA/IP level, then projects end-of-season outcomes.

**Stats evaluated:**

| Player Type | Stats |
|-------------|-------|
| Hitters | wOBA, HR rate, K%, BB%, SB rate, AVG, OPS |
| Pitchers | ERA, FIP, K%, BB%, WHIP |

**Metrics computed per (season, checkpoint, method, stat) combination:**
- RMSE (root mean squared error)
- MAE (mean absolute error)
- R-squared (correlation with actual outcomes)
- N (number of players in the test set)

**Output:** Results are saved to `data/results/` as JSON and CSV files with per-player detail rows for drill-down analysis.

### Analysis Scripts (`scripts/analysis/`)

Five targeted analysis scripts that each investigate a specific projection parameter or technique. All output professionally formatted Excel workbooks (via openpyxl) with conditional formatting, formulas, and cell comments to the `analysis/` directory.

| Script | What It Tests | Key Parameters |
|--------|--------------|----------------|
| `analyze_dampening.py` | Opposing pitcher quality adjustments — tests 7 dampening levels (0.40–0.70) across 7 SIERA ratio buckets | Optimal dampening factor for matchup adjustments |
| `analyze_park_factors.py` | Park factor strength multipliers — tests 9 levels (0.60–1.00) for HR and R rate adjustments | How aggressively to apply park factors |
| `analyze_xwoba_regression.py` | Statcast predictive power — tests whether prior-season xwOBA predicts future wOBA better than traditional wOBA, with blend ratios from 100/0 to 30/70 | Optimal xwOBA vs wOBA blend |
| `analyze_platoon_replacement.py` | Platoon-only vs pitcher-quality-only vs multiplicative adjustment approaches for wOBA prediction | Best matchup adjustment method |
| `analyze_dynamic_weights.py` | Optimal traditional/Statcast blend weights at each PA checkpoint (200/350/450) using scipy optimization | Whether static 50/50 weights should vary by sample size |

Each script reads from `backtest_data.sqlite` and uses walk-forward validation (same as the harness — never uses future data). The Excel outputs include summary sheets with RMSE comparisons and detail sheets for manual inspection.

### Parameter Optimizer (`scripts/optimize_parameters.py`)

Uses `scipy.optimize` (Nelder-Mead method) to find optimal values for the projection engine's 8 tunable parameters by minimizing RMSE against historical end-of-season outcomes.

**Parameters optimized:**

| Parameter | Current Value | Bounds | What It Controls |
|-----------|--------------|--------|-----------------|
| `w_full_season_trad` | 0.25 | 0.05–1.00 | Full-season traditional stats weight |
| `w_last_30_trad` | 0.15 | 0.05–1.00 | Last-30-day traditional stats weight |
| `w_last_14_trad` | 0.10 | 0.05–1.00 | Last-14-day traditional stats weight |
| `w_full_season_statcast` | 0.30 | 0.05–1.00 | Full-season Statcast weight |
| `w_last_30_statcast` | 0.20 | 0.05–1.00 | Last-30-day Statcast weight |
| `phase1_dampening` | 0.50 | 0.20–0.80 | Early-season regression dampening |
| `phase2_dampening` | 0.35 | 0.20–0.80 | Mid-season regression dampening |
| `signal_threshold` | 0.030 | 0.010–0.060 | Buy/sell signal sensitivity (xwOBA - wOBA delta) |

**Constraint:** The 5 blend weights (first 5 parameters) must sum to 1.0. The optimizer enforces this via re-normalization after each iteration.

**Walk-forward evaluation:** For each test season, simulates partial-season data at 3 PA checkpoints (200/350/450 PA for hitters, 50/100/140 IP for pitchers) blended with prior-season data, then measures prediction error against actual end-of-season results.

**Objective function weighting:** Hitter error counts for 60%, pitcher error for 40% — reflecting the larger roster share of position players.

**Output:** Results saved to `data/optimization/` with before/after parameter comparisons and per-stat RMSE improvements.

---

## 15. Quality Gate Process

The backtesting infrastructure enforces a quality gate before any projection engine changes reach production.

**Thresholds:**

| Gate | Threshold | Consequence |
|------|-----------|-------------|
| Overall RMSE improvement | Current Model must beat Marcel by >= 5% | If not met: PAUSE and rework the projection engine |
| Per-stat regression | No individual stat may regress > 3% vs Marcel | If any stat regresses beyond 3%: investigate and fix before proceeding |

**How it works:**

1. Run `scripts/backtest_harness.py` to generate RMSE/MAE/R-squared metrics for all 4 projection methods
2. Compare the Current Model's aggregate RMSE against Marcel's across all seasons and checkpoints
3. If the Current Model's RMSE is not at least 5% lower than Marcel's, the projection engine needs rework before proceeding to Phase 2 enhancements
4. Check each individual stat (wOBA, HR rate, K%, BB%, etc.) — none may show > 3% RMSE regression compared to Marcel

**Executive methodology document:** The full backtesting rationale, methodology, and results interpretation guide lives at `docs/BACKTESTING_METHODOLOGY.md`. This document explains walk-forward validation, why Marcel is the benchmark, and how to interpret the harness output.

**Decision flow:**

```
Run backtest_harness.py
        │
        ▼
Overall RMSE >= 5% better than Marcel?
        │
   No ──┤──── PAUSE: rework projection engine
        │
   Yes  ▼
Any stat regressed > 3% vs Marcel?
        │
   Yes ─┤──── Fix regressed stats before continuing
        │
   No   ▼
Proceed to Phase 2 enhancements
```

---

## 16. Phase 5: Self-Optimization (April 30 Hold)

The parameter optimizer (`scripts/optimize_parameters.py`) can automatically tune the projection engine's 8 parameters using historical data. However, automatically applying optimized parameters to production is gated behind a date and feature flag.

### Why the Hold

Optimized parameters derived from historical backtesting (2019–2025) could overfit to past patterns. The April 30, 2026 hold ensures enough 2026 in-season projection log data exists to validate that optimized parameters actually improve live projections — not just historical ones.

### Two Modes

| Mode | Command | What It Does |
|------|---------|-------------|
| **Validation** | `--mode validation` | Runs optimization against historical data only. Outputs recommended parameters to `data/optimization/` for manual review. Safe to run anytime. |
| **Production** | `--mode production` | Would apply optimized parameters to `app/config.py`. **Blocked until April 30, 2026** — the script checks `date.today()` and refuses to run in production mode before then. |

### Feature Flag

The `ENABLE_AUTO_TUNING` flag in `app/config.py` controls whether the production app accepts auto-tuned parameters. Until set to `True`, the app uses the hardcoded default weights defined in the projection service.

**Current state:** `ENABLE_AUTO_TUNING = False` (default). Will be evaluated for activation after April 30, 2026, pending validation results.

### Parameters Tuned

The optimizer tunes the same 8 parameters listed in [Section 13](#parameter-optimizer-scriptsoptimize_parameterspy). The 5 blend weights are constrained to sum to 1.0, and all parameters are bounded to prevent extreme values.

### Workflow

1. Run the data pipeline to ensure `backtest_data.sqlite` is current
2. Run the optimizer in validation mode: `uv run python -m scripts.optimize_parameters --mode validation`
3. Review output in `data/optimization/` — compare optimized vs current RMSE
4. After April 30, 2026: run against early-season 2026 projection logs to confirm improvement
5. If validated: set `ENABLE_AUTO_TUNING = True` in config and run in production mode
6. If not validated: keep current parameters and investigate why historical gains don't transfer
