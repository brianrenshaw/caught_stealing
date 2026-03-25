# Changelog

All notable changes to the Fantasy Baseball Analysis App are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added
- **Mobile responsive layout** — hamburger menu, full-width chat panel, responsive padding, tables, and charts for phone/tablet use
- **Fly.io deployment config** — Dockerfile, fly.toml, .dockerignore for cloud deployment with persistent SQLite volume
- **Health check endpoint** — `GET /health` for Fly.io monitoring
- **Configurable deployment settings** — CORS origins, cache dir, data dir, and headless mode via environment variables

### Fixed
- **Intel refresh timeout** — added 5-minute subprocess timeout (was infinite), updated estimate from "30 seconds" to "2-3 minutes (Claude Opus)", added live elapsed-time counter

---

## 2026-03-24

### Added
- **Cardinals CSS design system** — Midnight Navy structure, Cardinal Red accents, Roboto Slab editorial typography, warm pink hover states, SVG Heroicon sidebar nav, shadow-based card system, Cardinals badge system (ADD/DROP/WATCH/STREAM), reusable Jinja2 component macros
- **Projection Analysis tab** — weekly accuracy tracking (Yahoo vs app projections), league-wide MAE, per-team predictability rankings, automated markdown accuracy reports
- **League Points dashboard revamp** — standings with live scoreboard, league-wide weekly snapshots, integrated with projection analysis
- **Sortable tables everywhere** — shared `table-sort.js` with click-to-sort, search/filter, and fetch-and-append for surfacing unlisted players
- **Stats Explorer overhaul** — dropdown stat selectors, distribution comparison overlay, player spotlight panel (rolling trends, percentile bars, radar chart), click-to-spotlight from charts, roster filter (FA/rostered/my team/all)
- **Content intelligence pipeline** — RSS blog ingester (FanGraphs, Pitcher List, RotoWire), podcast downloader (CBS, FantasyPros, Locked On, In This League) to MacWhisper watch folder, transcript collector with filesystem watcher, Claude Opus daily analysis with per-player metadata tables and source citations
- **Intel tab** — browse daily/weekly AI-generated briefings with section navigation, on-demand refresh, Obsidian-compatible markdown output with TOC directives
- **launchd automation** — 3 AM daily content ingest + transcript watcher daemon
- Fantasy team ownership displayed across all search results and player tables
- Keyboard arrow navigation on all search dropdowns
- "Look for" guidance on every stat display across all pages
- Enriched stat tooltips with fantasy relevance, good/avg/bad ranges, and direction hints

### Changed
- Plotly charts use white backgrounds with Cardinals color series
- Dark navy tooltips with white text
- Navy sync buttons, Cardinal Red for AI-powered buttons

### Fixed
- Obsidian directive cleanup in markdown rendering

---

## 2026-03-23

### Added
- **Advanced analytics** — xwOBA, ISO, Barrel%, K%, Sprint Speed, xERA, SIERA, GB%, HR/FB%, gmLI on projections page with show/hide toggle
- **Dashboard matchup analysis** — weekly H2H with Yahoo projected, app projected, and actual points; player-by-player breakdown with per-category stats
- **Matchup quality model** — four-layer system: opposing pitcher quality (SIERA + K%/BB%), team offense (wRC+), park factors with home-park neutralization, regressed platoon splits per Tango's The Book
- **Weekly waiver projections** — period dropdown (ROS/This Week/Next Week), two-start pitcher detection, reliever role/opportunity badges, closer vacancy detection, Statcast breakout indicators
- **Dashboard lineup optimizer** — matchup-adjusted projections with PuLP optimizer swap suggestions and AI start/sit analysis
- **Weekly Outlook** — narrative analyst column with H2H matchup preview, standings context, schedule/weather, Cardinals Corner, Ithilien Watch
- **Steamer ROS projections** — primary projection source with regression; dual columns (Steamer + App Proj) in waiver table
- **AI content rendering** — marked.js for markdown, Copy (rich text clipboard) and Email (mailto) buttons on all analysis partials
- Multi-position eligibility from Yahoo for optimizer accuracy
- Injury integration via MLB Official Injury Report with DTD/IL badges
- Game context in AI prompts: venues, park factors, weather, probable starters
- Markdown rendering for chat assistant responses

### Changed
- Weekly Outlook uses professional ESPN/Athletic voice (removed Galactic Empire theming)
- Dual projections: Yahoo + app-calculated with discrepancy analysis
- Fantasy team tags on all player mentions, e.g. (Empire), (Ithilien), (FA)
- Lower sync cooldown from 5 minutes to 1 minute
- ROS projection rewritten to use actual stats × remaining games ÷ 162

### Fixed
- Empty waiver results: added season fallback, free-agent filter, per-player error handling
- Projection inflation in waiver scoring
- Duplicate row errors for two-way players (filter StatcastSummary by player_type)
- Spring training games counted in weekly projections (filter game_type=R)
- Reliever IP overestimation (use actual appearance rate, not flat 0.7/game)
- Batting stats loader missing ISO, BABIP, K%, BB%, WAR columns
- First-click HTMX bug on AI content partials
- Template copy/email button scoping

---

## 2026-03-22

### Added
- **Initial project setup** — FastAPI + Jinja2 + HTMX + Tailwind CSS + Plotly.js + SQLite, Yahoo Fantasy API integration via yfpy, pybaseball for FanGraphs/Statcast, MLB-StatsAPI for live data, PuLP optimizer, APScheduler, diskcache, Claude AI assistant
- **Dashboard** — team overview, standings, roster summary, sync controls
- **Roster page** — full roster display with lineup positions
- **Trade analyzer** — VORP-based trade calculator with z-score method, search autocomplete + player chips UI
- **Waiver wire** — composite scoring with recommendations
- **Stats Explorer** — scatter plots, distributions, histograms with Plotly.js; statcast data, luck chart (xwOBA vs wOBA), season selector, player highlight search
- **Projections page** — Steamer + ZiPS + ATC blended consensus projections
- **Matchups page** — head-to-head matchup views
- **Player comparison tool** — Baseball Savant-style side-by-side with 7 tabs (Overview percentile bars, Stat Table, Projections, Trends, Splits, Radar Chart), HTML5 drag-and-drop, URL-shareable comparisons, localStorage dock
- **Clickable player popups** — modal with full batting/pitching stats and Statcast metrics, per-season browsing
- **Info tooltip system** — ⓘ icons on every stat column header with definitions, benchmarks, and fantasy relevance
- **Multi-season sync** — dropdown to bulk-load historical data across multiple years
- **AI chat assistant** — Claude-powered sidebar chat for fantasy advice
- **ETL pipeline** — Yahoo sync, FanGraphs/Statcast stats, projection blending, scheduled via APScheduler
- **Cross-platform player ID mapping** — Yahoo, FanGraphs, MLBAM, Baseball Reference
- User Guide documentation

### Fixed
- Stats Explorer statcast column mappings (est_ba→xba, est_slg→xslg, est_woba→xwoba)
- MultipleResultsFound error in comparable players query
- Trade values always showing "fair" (season mismatch fix)
- XSS vulnerabilities via data attributes + tojson filter
- N+1 query issues in player profiles (14→3 queries)
- Plotly memory leaks (purge before newPlot)

### Security
- Restricted CORS origins
- Input validation bounds on all form inputs
- Added DB indexes on player_id/season across all models
