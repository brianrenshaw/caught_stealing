# Developer's Playbook

A comprehensive technical guide to the Fantasy Baseball Analysis App — its architecture, data sources, algorithms, and how everything fits together.

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

### FanGraphs (`app/services/fangraphs_service.py`)

**What it provides:** Traditional and advanced batting/pitching stats — AVG, OBP, SLG, wOBA, wRC+, ISO, BABIP, FIP, xFIP, SIERA, K%, BB%, WAR, and more.

**Why:** FanGraphs is the gold standard for advanced baseball analytics. Their metrics (FIP, xFIP, SIERA, wRC+) are better predictors of future performance than raw stats. We use these for projection blending — traditional stats get 50% of the projection weight.

**How it works:**
- Actual stats fetched via `pybaseball` library (which scrapes FanGraphs leaderboards)
- Retry logic: 3 attempts with 5-second delays between failures
- Column name mapping normalizes FanGraphs output to our DB schema
- Fetches full-season, last-30-day, and last-14-day windows for recency weighting
- `qual=0` (no minimum PA/IP) to capture all rostered players

**Steamer ROS projections** are fetched separately via the FanGraphs projections API (`https://www.fangraphs.com/api/projections?type=steamer`) using `httpx`. This returns full counting stats (HR, 2B, BB, K, IP, SV, HLD, ER, etc.) which are converted to league-specific fantasy points using our scoring rules. Stored in the `projections` table with `system='steamer_ros'` and on `player_points.steamer_ros_points` after conversion. Matched to players via `fangraphs_id` or `mlbam_id` (the API returns `xMLBAMID`).

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
8. Fetch Steamer ROS projections from FanGraphs projections API (full counting stats, converted to league-specific fantasy points)
9. Calculate player points from loaded stats (includes attaching Steamer ROS points)

**Loading patterns:**
- Match players by `fangraphs_id` or `mlbam_id`
- Upsert by `(player_id, season, period, source)`
- `_safe_val()` filters out NaN/inf values to prevent database corruption

---

## 5. Services Deep Dive

### Projection Engine (`app/services/projection_service.py`)

The projection engine blends traditional stats with Statcast expected stats to produce rest-of-season (ROS) projections.

**Weight System:**

| Data Source | Weight | Why |
|-------------|--------|-----|
| Full season traditional stats | 25% | Baseline performance |
| Last 30 days traditional stats | 15% | Recent form |
| Last 14 days traditional stats | 10% | Hot/cold streaks |
| Full season Statcast expected stats | 30% | Best long-term predictor |
| Last 30 days Statcast expected stats | 20% | Recent quality-of-contact trends |

Traditional stats get 50% total weight, Statcast gets 50%. This is intentional — Statcast expected stats (xBA, xSLG, xwOBA) strip out luck (BABIP variance, defensive alignment) and measure the true quality of a player's at-bats.

**Counting stats projection (HR, R, RBI, SB):**
1. Calculate per-PA rates from full season, last 30, and last 14 data
2. Weighted-average the rates using the weights above
3. Estimate remaining plate appearances based on season progress
4. Multiply rate × remaining PA, then add already-accumulated totals

**Rate stats projection (AVG, OBP, SLG):**
- Blends traditional rates with Statcast expected stats (xBA, xSLG, xwOBA) using the same weight system

**Pitcher ERA projection:**
- Weights: actual ERA (15%), FIP (25%), xFIP (25%), last-30 ERA (10%), last-30 FIP (10%), last-14 ERA (5%)
- FIP/xFIP are weighted more heavily than actual ERA because they're better predictors (strip out defense and sequencing luck)

**Remaining IP estimation:**
- Starters: 6 IP/start × 32 starts = 192 IP full-season baseline
- Relievers: 1 IP/appearance × 65 appearances = 65 IP baseline
- Prorated by season progress

**Confidence score (0–100%):**
- PA/IP contribution: min(PA/400, 1.0) × 60% (more data = more confident)
- Statcast availability bonus: +20% if expected stats exist
- Season progress: 0–20% scaled by how far into the season we are

**Buy/sell signals:**
- Buy low: xwOBA exceeds actual wOBA by ≥ 0.030 (player is unlucky, regression coming)
- Sell high: actual wOBA exceeds xwOBA by ≥ 0.030 (player is lucky, regression coming)

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
- **App Projected** — Internal blended projection (Statcast + traditional stats, see Projection Engine)
- **Steamer ROS** — FanGraphs Steamer projections converted to league scoring
- **Actual Points** — What the player has scored this season

Disagreements between App Projected and Steamer highlight buy-low/sell-high opportunities.

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

1. **ROS mode** (`score_free_agents`): Uses Steamer ROS projections (with regression) when available, falls back to app projection. Both displayed as dual columns (Steamer + My Proj) in the waiver table.
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
5. Compute weekly projections (matchup-aware)
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

**AI content rendering:** All AI-generated content (weekly outlook, waiver analysis, lineup analysis, chat) renders via Marked.js client-side markdown. Copy and Email buttons on analysis partials copy rich HTML to clipboard / open mailto with subject pre-filled.

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
| **App Projection** | `project_batter_ros_points()` / `project_pitcher_ros_points()` | Same scaling method as the weekly dashboard: actual counting stats scaled proportionally to remaining games, scored with league weights. During offseason (< 30 games remaining), projects a full 162-game season from prior year rates. After Week 2 of the new season, switches to live ROS. |
| **Steamer ROS** | `_build_steamer_points_map()` | Reads Steamer projections from `projections` table (system='steamer_ros'), groups counting stats by player, runs through `calculate_batter_points()` / `calculate_pitcher_points()`. Includes regression to the mean and aging curves. Stored on `player_points.steamer_ros_points`. |

The waiver wire prefers Steamer (more accurate for long-term projections) and shows both columns. The weekly dashboard uses its own 4-phase matchup-adjusted model which is more accurate for per-week decisions.

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
