# Fantasy Baseball Analysis App

## Project Overview
Personal fantasy baseball analysis web app connected to a Yahoo Fantasy Baseball league.
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
│   │   ├── projection_service.py # Fetch + blend projections
│   │   ├── external_projections.py # FanGraphs projection fetching
│   │   ├── comparison_service.py # Player comparison logic + search
│   │   ├── matchup_service.py    # Head-to-head matchup analysis
│   │   ├── rankings_service.py   # Player ranking calculations
│   │   ├── splits_service.py     # Player splits data
│   │   ├── optimizer_service.py  # PuLP lineup optimizer
│   │   ├── trade_service.py      # VORP-based trade analyzer
│   │   ├── waiver_service.py     # Waiver wire scorer + AI analysis
│   │   ├── schedule_service.py   # MLB schedule, team games, weather data
│   │   ├── weekly_lineup_service.py # Weekly lineup optimization + AI outlook
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
│           ├── charts.js         # Plotly chart builders (scatter, bar, histogram, radar)
│           ├── comparison.js     # Player comparison tool logic
│           └── tooltips.js       # Info tooltip system
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
```

## Development Commands
```bash
uv run uvicorn app.main:app --reload --port 8000    # Start dev server
uv run python -m app.etl.pipeline                     # Run ETL manually
uv run ruff check .                                   # Lint
uv run ruff format .                                  # Format
uv run pytest                                         # Test
```

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
