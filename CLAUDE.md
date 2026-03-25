# Fantasy Baseball Analysis App

## Project Overview
Personal fantasy baseball analysis web app — **Lankford Legends** — connected to a Yahoo Fantasy Baseball league.
Provides roster optimization, trade analysis, waiver wire recommendations, player projections, and an interactive stats dashboard.

## Tech Stack
- **Package Manager**: uv (always use `uv add` instead of `pip install`)
- **Backend**: FastAPI with Jinja2 templates
- **Frontend**: HTMX + Tailwind CSS (via CDN) + Plotly.js for charts
- **Database**: SQLite via SQLAlchemy (async with aiosqlite)
- **Yahoo API**: yfpy library for Yahoo Fantasy Sports integration
- **Baseball Data**: pybaseball for FanGraphs, Statcast, Baseball Reference data
- **MLB Live Data**: MLB-StatsAPI for rosters, injuries, schedules
- **AI Assistant**: Anthropic Claude API for in-app chat assistant
- **Optimization**: PuLP for lineup optimization (Integer Linear Programming)
- **Scheduling**: APScheduler for automated data refreshes
- **Caching**: diskcache for local response caching
- **Linting**: Ruff (dev dependency)

## Project Structure
```
fantasy-baseball/
├── CLAUDE.md
├── pyproject.toml
├── .env                          # Yahoo API credentials (never commit)
├── .gitignore
├── app/
│   ├── __init__.py
│   ├── main.py                   # FastAPI app entry point
│   ├── config.py                 # Settings via pydantic-settings
│   ├── database.py               # SQLAlchemy engine + session
│   ├── models/                   # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── player.py             # Players table with cross-platform IDs
│   │   ├── batting_stats.py      # Batting stats by period (full_season, last_30, etc.)
│   │   ├── pitching_stats.py     # Pitching stats by period
│   │   ├── statcast_summary.py   # Statcast metrics (EV, barrel%, xwOBA, etc.)
│   │   ├── player_splits.py      # vs LHP/RHP, home/away splits
│   │   ├── stats.py              # Legacy generic stats table
│   │   ├── projection.py         # Projection systems (Steamer, ZiPS, ATC, etc.)
│   │   ├── roster.py             # Yahoo league rosters
│   │   ├── league_team.py        # League team standings
│   │   ├── league_week_snapshot.py # League-wide weekly standings + scoreboard snapshots
│   │   ├── player_points.py      # Computed fantasy points by period (ROS, weekly)
│   │   ├── weekly_matchup.py     # H2H matchup snapshots (projected vs actual)
│   │   ├── trade_value.py        # Computed trade values
│   │   ├── conversation.py       # Chat assistant conversation history
│   │   └── sync_log.py           # ETL sync history/status
│   ├── services/                 # Business logic layer
│   │   ├── __init__.py
│   │   ├── yahoo_service.py      # Yahoo Fantasy API via yfpy
│   │   ├── stats_service.py      # pybaseball data retrieval (async via executor)
│   │   ├── fangraphs_service.py  # FanGraphs stats with retry logic
│   │   ├── statcast_service.py   # Statcast data fetching + processing
│   │   ├── mlb_service.py        # MLB Stats API for live data
│   │   ├── player_service.py     # Player profile aggregation
│   │   ├── projection_service.py # Statcast buy/sell signals + trend detection (supplements consensus)
│   │   ├── external_projections.py # Fetch Steamer/ZiPS/ATC and blend into consensus projections
│   │   ├── comparison_service.py # Player comparison logic + search
│   │   ├── matchup_service.py    # Head-to-head matchup analysis
│   │   ├── rankings_service.py   # Player ranking calculations
│   │   ├── splits_service.py     # Player splits data
│   │   ├── optimizer_service.py  # PuLP lineup optimizer
│   │   ├── trade_service.py      # VORP-based trade analyzer
│   │   ├── waiver_service.py     # Waiver wire scorer + AI analysis
│   │   ├── schedule_service.py   # MLB schedule, team games, weather data
│   │   ├── weekly_lineup_service.py # Weekly lineup optimization + AI outlook
│   │   ├── weekly_matchup_service.py # H2H matchup snapshots, league scoreboard, projection breakdowns
│   │   ├── points_service.py     # Fantasy points calculation using league scoring weights
│   │   ├── matchup_quality_service.py # Park factors, platoon splits, opposing pitcher adjustments
│   │   ├── projection_accuracy_service.py # Weekly + season accuracy reports (markdown)
│   │   ├── assistant.py          # Claude AI chat assistant
│   │   ├── assistant_tools.py    # Tool functions for the assistant
│   │   └── id_mapper.py          # Cross-platform player ID mapping
│   ├── routes/                   # FastAPI route handlers
│   │   ├── __init__.py
│   │   ├── dashboard.py          # Main dashboard views
│   │   ├── roster.py             # Roster + lineup optimization
│   │   ├── trades.py             # Trade analyzer (search + select UI)
│   │   ├── waivers.py            # Waiver recommendations
│   │   ├── projections.py        # Projection explorer
│   │   ├── stats_dashboard.py    # Stats Explorer with Plotly charts
│   │   ├── player.py             # Player profile pages
│   │   ├── comparison.py         # Player comparison tool
│   │   ├── matchups.py           # Head-to-head matchup views
│   │   ├── intel.py              # Intel tab — daily analysis reports
│   │   ├── projection_analysis.py # Projection accuracy tracking (Yahoo vs app)
│   │   ├── league_dashboard.py   # League Points dashboard (H2H scoring focus)
│   │   ├── assistant.py          # AI chat assistant routes
│   │   └── api.py                # JSON API endpoints for HTMX
│   ├── templates/                # Jinja2 HTML templates
│   │   ├── base.html             # Layout with Tailwind + HTMX + Plotly CDN
│   │   ├── dashboard.html
│   │   ├── roster.html
│   │   ├── trades.html
│   │   ├── waivers.html
│   │   ├── projections.html
│   │   ├── stats_dashboard.html
│   │   ├── compare.html
│   │   ├── matchups.html
│   │   ├── projection_analysis.html # Projection accuracy tracker
│   │   ├── league_dashboard.html # League Points dashboard
│   │   ├── intel.html            # Intel reports viewer
│   │   └── partials/             # HTMX partial templates
│   ├── etl/                      # Data pipeline
│   │   ├── __init__.py
│   │   ├── pipeline.py           # Main ETL orchestrator
│   │   ├── extractors.py         # Pull from Yahoo, pybaseball, MLB API
│   │   ├── transformers.py       # Normalize IDs, calc derived stats
│   │   └── loaders.py            # Write to SQLite
│   └── static/                   # Static assets (minimal - CDN preferred)
│       ├── css/
│       │   └── custom.css
│       └── js/
│           ├── charts.js         # Plotly chart builders (scatter, bar, histogram, radar, rolling)
│           ├── comparison.js     # Player comparison tool logic
│           ├── table-sort.js     # Sortable tables with search, filter, and fetch-append
│           ├── markdown-actions.js # Markdown rendering + Obsidian directive cleanup
│           └── tooltips.js       # Info tooltip system with fantasy context
├── scripts/                      # Standalone backtesting & content tools
│   ├── data_pipeline.py          # Historical data download (2015-2025)
│   ├── backtest_harness.py       # Walk-forward projection testing
│   ├── optimize_parameters.py    # scipy parameter tuning (April 30 hold)
│   ├── blog_ingest.py            # RSS blog fetcher (FanGraphs, Pitcher List, RotoWire)
│   ├── podcast_transcriber.py    # Podcast downloader → MacWhisper watch folder (CBS, FantasyPros, Locked On, In This League)
│   ├── transcript_collector.py   # Collects MacWhisper output → formatted markdown
│   ├── daily_analysis.py         # Claude-powered analysis of content + league data → MD + PDF
│   ├── daily_content_ingest.sh   # Daily wrapper (launchd runs at 3 AM); generates PDFs with Cardinals CSS, moves to sync folder for mobile
│   ├── capture_yahoo_token.py   # Yahoo OAuth token capture for Fly.io
│   └── analysis/                 # Analysis scripts → Excel reports
├── data/                         # Backtesting data (raw CSVs, results, optimization)
│   └── content/                  # Ingested blogs + podcast transcripts
│       ├── blogs/                # Markdown articles from RSS feeds
│       ├── transcripts/          # Final formatted transcripts with frontmatter
│       ├── analysis/             # Claude-generated daily reports (Obsidian watches this)
│       ├── audio/
│       │   ├── pending/          # MacWhisper watches this folder (.mp3 + .json sidecar)
│       │   └── transcribed/      # MacWhisper outputs .txt here
│       └── manifest.json         # Index of all ingested content
├── docs/                         # Documentation
│   ├── AI_FEATURES.md            # Comprehensive AI features guide
│   ├── BACKTESTING_METHODOLOGY.md
│   └── USER_GUIDE.md
└── tests/
    ├── __init__.py
    ├── test_optimizer.py
    ├── test_trade_values.py
    └── test_waiver_scorer.py
```

## Key Dependencies
```
fastapi
uvicorn[standard]
jinja2
sqlalchemy[asyncio]
aiosqlite
yfpy
pybaseball
MLB-StatsAPI
pulp
apscheduler
diskcache
pydantic-settings
python-dotenv
httpx
pandas
numpy
python-multipart
anthropic              # Claude AI assistant
feedparser             # RSS feed parsing for blog ingestion
```

## Database Schema (Core Tables)

### players
- id (PK, integer autoincrement)
- name (text, not null)
- team (text) — MLB team abbreviation
- position (text) — primary eligible position(s), comma-separated
- yahoo_id (text, unique, nullable)
- fangraphs_id (text, unique, nullable)
- mlbam_id (text, unique, nullable)
- bbref_id (text, unique, nullable)
- created_at, updated_at (datetime)

### stats
- id (PK)
- player_id (FK → players)
- season (integer)
- stat_type (text) — e.g. "batting", "pitching"
- stat_name (text) — e.g. "HR", "ERA", "xwOBA"
- value (float)
- source (text) — "fangraphs", "statcast", "bbref"
- date_range (text, nullable) — for rolling/recent splits
- updated_at (datetime)

### projections
- id (PK)
- player_id (FK → players)
- season (integer)
- system (text) — "steamer", "zips", "atc", "thebat", "blended"
- stat_name (text)
- projected_value (float)
- updated_at (datetime)

### rosters
- id (PK)
- league_id (text)
- team_id (text)
- team_name (text)
- player_id (FK → players)
- roster_position (text) — "C", "1B", "OF", "BN", "SP", "RP", etc.
- is_my_team (boolean)
- updated_at (datetime)

### weekly_matchup_snapshots
- id (PK)
- season (integer), week (integer) — unique constraint
- my_team_id, my_team_name, opponent_team_id, opponent_team_name
- my_projected_points, opponent_projected_points (float) — Yahoo projections (frozen)
- my_app_projected_points, opponent_app_projected_points (float) — App projections (frozen)
- my_actual_points, opponent_actual_points (float) — live actuals
- my_projected_breakdown, opponent_projected_breakdown (JSON) — per-player stats
- my_actual_breakdown, opponent_actual_breakdown (JSON)
- created_at, updated_at (datetime)

### league_week_snapshots
- id (PK)
- season (integer), week (integer), team_id (text) — unique constraint
- team_name, is_my_team
- rank, wins, losses, ties, points_for, points_against — standings snapshot
- opponent_team_id, opponent_team_name
- yahoo_projected_points, actual_points, opponent_actual_points (float)
- app_projected_points (float) — only for my team
- created_at, updated_at (datetime)

### player_points
- id (PK)
- player_id (FK → players), season, period, player_type
- actual_points, projected_ros_points, steamer_ros_points (float)
- points_per_pa, points_per_ip, points_per_start, points_per_appearance (float)
- positional_rank (integer), surplus_value (float)
- updated_at (datetime)

### trade_values
- id (PK)
- player_id (FK → players)
- surplus_value (float) — value above replacement
- positional_rank (integer)
- z_score_total (float) — sum of z-scores across counting categories
- updated_at (datetime)

## Yahoo Fantasy API Setup
1. Register at https://developer.yahoo.com/apps/create/
2. Set app type to "Installed Application"
3. Check "Fantasy Sports" under API Permissions
4. Save Client ID and Client Secret to .env
5. First run triggers browser-based OAuth flow — token auto-refreshes after that

## Environment Variables (.env)
```
YAHOO_CLIENT_ID=your_client_id
YAHOO_CLIENT_SECRET=your_client_secret
YAHOO_LEAGUE_ID=your_league_id
YAHOO_GAME_KEY=mlb  # or specific year key like 431
DATABASE_URL=sqlite+aiosqlite:///./fantasy_baseball.db
ANTHROPIC_API_KEY=your_api_key
AUTH_PASSWORD=your_password
YAHOO_ACCESS_TOKEN_JSON=  # JSON token for headless Yahoo OAuth (Fly.io)
CONTENT_DIR=data/content  # Override for Fly.io: /data/content
HEADLESS=false            # true on Fly.io (disables browser OAuth)
CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000  # Add Fly.io domain for production
```

## Projection Architecture
All features (trades, waivers, optimizer, weekly matchup) derive from consensus
projections (Steamer + ZiPS + ATC blended). Consensus counting stats are converted
to fantasy points using league scoring. Statcast data provides buy/sell signals and
trend detection on top of the consensus base.

## Development Commands
```bash
uv run uvicorn app.main:app --reload --port 8000    # Start dev server
uv run python -m app.etl.pipeline                     # Run ETL manually
uv run ruff check .                                   # Lint
uv run ruff format .                                  # Format
uv run pytest                                         # Test
uv run python -m scripts.data_pipeline                # Download historical data
uv run python -m scripts.backtest_harness             # Run backtesting
uv run python -m scripts.optimize_parameters --mode validation  # Parameter tuning
uv run python -m scripts.blog_ingest --days 7               # Fetch recent blog articles
uv run python -m scripts.podcast_transcriber --days 7        # Download podcasts to MacWhisper watch folder
uv run python -m scripts.transcript_collector                # Collect finished MacWhisper transcripts
uv run python -m scripts.daily_analysis                      # Generate daily analysis reports
uv run python -m scripts.daily_analysis --dry-run            # Preview prompts without API calls
./scripts/daily_content_ingest.sh                            # Run full daily pipeline manually

# Fly.io Deployment
flyctl deploy                                              # Deploy to Fly.io
flyctl logs --no-tail                                      # Check server logs
flyctl ssh console                                         # SSH into server
flyctl ssh sftp shell                                      # Upload files to volume
uv run python -m scripts.capture_yahoo_token               # Capture Yahoo OAuth token for Fly.io
```

## Fly.io Deployment
App runs at `https://fantasy-baseball-br.fly.dev/` on Fly.io with:
- **Persistent volume** mounted at `/data` — stores SQLite DB, Yahoo tokens, content, cache
- **fly.toml** config: `auto_stop_machines = 'off'`, `min_machines_running = 1` (always-on, ~$3/mo)
- **Health check** at `GET /health` every 30s
- **Secrets**: `YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`, `YAHOO_LEAGUE_ID`, `ANTHROPIC_API_KEY`, `AUTH_PASSWORD`, `YAHOO_ACCESS_TOKEN_JSON`
- **Env vars** (in fly.toml): `DATABASE_URL`, `CACHE_DIR`, `DATA_DIR`, `CONTENT_DIR`, `HEADLESS`, `CORS_ORIGINS`

### Yahoo OAuth on Fly.io
Yahoo tokens expire hourly but auto-refresh. Token persistence:
1. Initial setup: run `uv run python -m scripts.capture_yahoo_token` locally
2. Set as Fly secret: `flyctl secrets set YAHOO_ACCESS_TOKEN_JSON='...'`
3. After each API call, refreshed tokens are saved to `/data/yahoo_token.json` (survives restarts)

### Daily Content Sync
`scripts/daily_content_ingest.sh` runs at 3 AM via launchd, then auto-uploads new reports to Fly volume via `flyctl ssh sftp`.

## Coding Conventions
- Use async/await for all database and HTTP operations
- Type hints on all function signatures
- Pydantic models for API request/response validation
- Services return domain objects, routes handle HTTP concerns
- Cache Yahoo API responses for 15 min, stats for 24 hours, projections for 7 days
- Add 0.5s delay between Yahoo API calls to avoid rate limiting
- Use pybaseball's built-in caching (`pybaseball.cache.enable()`)
- All player lookups go through id_mapper service — never hardcode IDs
- HTMX partials return HTML fragments, not full pages
- Plotly charts render client-side from JSON data endpoints

## Feature Priority
1. Yahoo league connection + roster display (validates API setup)
2. Stats dashboard with Plotly charts (validates data pipeline)
3. Projection blender (Steamer + ZiPS + ATC weighted average)
4. Roster optimizer (PuLP ILP solver for daily/weekly lineups)
5. Trade value calculator (VORP + z-score method)
6. Waiver wire recommender (composite scoring)
7. APScheduler for automated daily updates
