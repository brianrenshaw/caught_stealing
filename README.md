# Fantasy Baseball Analysis App

Personal fantasy baseball analysis web app connected to a Yahoo Fantasy Baseball league. Provides roster optimization, trade analysis, waiver wire recommendations, player projections, and an interactive stats dashboard.

## Tech Stack
- **Backend**: FastAPI + Jinja2
- **Frontend**: HTMX + Tailwind CSS + Plotly.js
- **Database**: SQLite (async via SQLAlchemy + aiosqlite)
- **Data Sources**: Yahoo Fantasy API (yfpy), pybaseball, MLB-StatsAPI

## Setup
1. Install [uv](https://docs.astral.sh/uv/)
2. Copy `.env.example` to `.env` and fill in Yahoo API credentials
3. `uv sync` to install dependencies
4. `uv run uvicorn app.main:app --reload --port 8000`

## Development
```bash
uv run ruff check .     # Lint
uv run ruff format .    # Format
uv run pytest           # Test
```
