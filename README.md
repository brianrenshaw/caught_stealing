# Caught Stealing

A personal fantasy baseball analysis app built on the Yahoo Fantasy API. Blends Statcast data, consensus projections (Steamer/ZiPS/ATC), and AI-powered analysis into a single dashboard for roster optimization, trade evaluation, waiver recommendations, and weekly matchup breakdowns.

Built by **Brian Renshaw** with [Claude Code](https://claude.ai/claude-code).

---

## Documentation

| Document | Description |
|----------|-------------|
| [User Guide](docs/USER_GUIDE.md) | Full walkthrough of every page and feature in the app |
| [Developer Playbook](DEVELOPERS_PLAYBOOK.md) | Architecture, services, data pipeline, and how to extend the app |
| [Intel Pipeline](docs/INTEL_PIPELINE.md) | Content ingestion system — blogs, podcasts, and AI-generated daily reports |
| [Backtesting Methodology](docs/BACKTESTING_METHODOLOGY.md) | Walk-forward projection validation and parameter optimization |
| [Changelog](CHANGELOG.md) | Version history and feature log |

---

## Features

- **Dashboard** — League standings, weekly matchup projections, and roster overview
- **Roster Optimizer** — ILP-based daily/weekly lineup optimization (PuLP)
- **Trade Analyzer** — VORP + z-score trade values with side-by-side comparison
- **Waiver Wire** — Composite scoring with Steamer ROS projections and Statcast signals
- **Stats Explorer** — Interactive Plotly charts across batting, pitching, and Statcast metrics
- **Player Comparison** — Head-to-head stat comparison with radar charts
- **Projections** — Blended consensus projections with buy/sell signal detection
- **Intel Reports** — AI-generated daily analysis from ingested blogs and podcasts
- **AI Assistant** — In-app Claude-powered chat with league context
- **Matchup Quality** — Park factors, platoon splits, and opposing pitcher adjustments
- **Projection Accuracy** — Weekly tracking of projection accuracy vs actuals

## Tech Stack

| Layer | Tools |
|-------|-------|
| Backend | FastAPI, SQLAlchemy (async), APScheduler |
| Frontend | HTMX, Tailwind CSS, Plotly.js, Jinja2 |
| Database | SQLite via aiosqlite |
| Data | Yahoo Fantasy API (yfpy), pybaseball, MLB-StatsAPI |
| AI | Anthropic Claude API |
| Optimization | PuLP (Integer Linear Programming) |
| Deployment | Docker, Fly.io |

## Quick Start

1. **Install [uv](https://docs.astral.sh/uv/)**

2. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your Yahoo API credentials and Anthropic API key
   ```

3. **Install dependencies and run**
   ```bash
   uv sync
   uv run uvicorn app.main:app --reload --port 8000
   ```

4. **First run** — The app will trigger a browser-based Yahoo OAuth flow. After authenticating, tokens refresh automatically.

> See the [User Guide](docs/USER_GUIDE.md) for a full walkthrough and the [Developer Playbook](DEVELOPERS_PLAYBOOK.md) for architecture details.

## Development

```bash
uv run ruff check .                          # Lint
uv run ruff format .                         # Format
uv run pytest                                # Test
uv run python -m app.etl.pipeline            # Run ETL manually
uv run python -m scripts.daily_analysis      # Generate daily intel reports
```

## Project Structure

```
app/
  main.py              # FastAPI entry point + auth middleware
  config.py            # pydantic-settings configuration
  database.py          # SQLAlchemy async engine
  models/              # ORM models (players, stats, projections, rosters, etc.)
  services/            # Business logic (Yahoo, stats, trades, waivers, optimizer, AI)
  routes/              # FastAPI route handlers
  templates/           # Jinja2 HTML templates
  etl/                 # Data pipeline (extract, transform, load)
  static/              # CSS + JS (charts, tables, tooltips)
scripts/               # Backtesting, data pipeline, content ingestion
docs/                  # User guide, methodology, pipeline docs
tests/                 # pytest test suite
```

## License

[MIT](LICENSE)
