# Fantasy Baseball Intel Pipeline

## What This Does

Every day, an automated pipeline collects expert fantasy baseball content from across the internet, cross-references it with your actual Yahoo Fantasy league data (roster, projections, standings, matchups), and produces a personalized intelligence report via the Claude API. The result is a set of markdown files — one comprehensive report plus individual sections — that surface in both the web app's Intel tab and Obsidian.

## How We Get the Sources

### Blogs (RSS feeds → markdown files)
The script `scripts/blog_ingest.py` fetches RSS feeds from:
- **FanGraphs Blog** — deep analysis, positional rankings, prospect coverage
- **Pitcher List** — SP rankings, projection comparisons, spring training breakdowns
- **RotoWire MLB News** — short player news blurbs (injuries, roster moves, spring performances)

Each article is downloaded, converted from HTML to markdown, and saved to `data/content/blogs/` with YAML frontmatter (title, source, date, author, URL).

### Podcasts (RSS → audio download → MacWhisper → transcript)
The script `scripts/podcast_transcriber.py` downloads episodes from:
- **Fantasy Baseball Today (CBS)** — daily expert roundtable
- **FantasyPros Baseball Podcast** — draft strategy, player analysis
- **Locked On Fantasy Baseball** — daily fantasy baseball coverage
- **In This League Fantasy Baseball** — community-driven analysis

Audio files land in `data/content/audio/pending/` alongside a JSON metadata sidecar (episode title, date, source, description). MacWhisper — running locally on the Mac — watches this folder and auto-transcribes each episode to `.txt`. A filesystem watcher (`scripts/transcript_collector.py`, running as a launchd daemon) detects new transcripts, wraps them in markdown with the metadata, and moves them to `data/content/transcripts/`.

### Scheduling
A launchd job runs `scripts/daily_content_ingest.sh` at 3 AM daily:
1. Collects any finished MacWhisper transcripts from the previous cycle
2. Fetches new blog articles
3. Downloads new podcast episodes (opens MacWhisper if needed)
4. Generates the analysis report

## What We Do With the Sources

### Content Loading
`scripts/daily_analysis.py` reads all markdown files from `blogs/` and `transcripts/`, parsing their YAML frontmatter for metadata (source name, date, URL). Blog articles are sent in full. Podcast transcripts (which can be 10-20K words each) are also sent in full — we use Claude Opus with a 1M token context window so nothing gets truncated.

On the first run, all available content is analyzed. On subsequent runs, only content published since the last report is included (tracked by the previous report's `generated_at` timestamp). Weekly reports (Saturday) always use all available content for a full-week review.

### League Data Loading
The script queries the app's SQLite database (`fantasy_baseball.db`) directly using sync `sqlite3`:

- **My roster** — every player I own with their consensus projection (Steamer + ZiPS + ATC blended), Steamer-only projection, surplus value above replacement, and positional rank
- **This week's H2H opponent** — pulled from the `weekly_matchup_snapshots` table (populated by the Yahoo API via yfpy), including opponent team name, projected points, and full opponent roster with projections
- **Ithilien's roster** — brother's team, tracked separately for the Sibling Rivalry section
- **Top 50 free agents** — unrostered players sorted by projected ROS points
- **League standings** — W-L records, points for/against, rankings from `league_teams`
- **Last week's matchup result** — actual points scored, per-player stat breakdowns (for Monday reports)
- **Weekly schedule** — game counts per MLB team from the MLB Stats API (`statsapi`)
- **Player links** — FanGraphs IDs from the `players` table, used to generate clickable profile URLs
- **Previous sentiments** — parsed from the last report's roster-intel section for week-over-week trend tracking

### The Single API Call
All of this — the full expert content, the complete league data, previous sentiments, and detailed section-by-section instructions — goes into a single Claude Opus API call. The system prompt establishes the analyst persona, formatting rules (markdown tables, player name conventions, source citation style), and league-specific context (scoring rules, Cardinals fan, Ithilien rivalry). The user message contains the section instructions, league data, and expert content.

Claude returns one long markdown document with `##` headers for each section. The script then:
1. **Splits** the response into individual sections by `##` header
2. **Links player names** to FanGraphs profiles (per-section, so every section gets links — not just first occurrence globally)
3. **Links source citations** to original article/episode URLs
4. **Writes** the full report and each section as separate `.md` files to `data/content/analysis/`

## How the Information Stays Accurate to the League

The projections and roster data come directly from the same database the web app uses, which syncs with Yahoo Fantasy via the yfpy library. This means:

- **Roster composition** is always current — when you add/drop a player in Yahoo, the next sync updates the DB, and the next report reflects it
- **Projections** are the same consensus blend (Steamer + ZiPS + ATC + FanGraphs DC + THE BAT X) used throughout the app for trade values, waiver scoring, and lineup optimization
- **Matchup opponent** is pulled from Yahoo's actual H2H schedule, not guessed
- **Standings** reflect real Yahoo league data
- **Surplus values and positional ranks** are computed by the app's `points_service` using the league's actual scoring rules (SV=7, HLD=4, OUT=1.5, ER=-4, K=-0.5, etc.)

The expert content provides the qualitative layer — what analysts are saying, spring training observations, injury news, role changes — that projections can't capture. Claude's job is to bridge the two: "Expert X says this about Player Y, and here's how that aligns or conflicts with what the numbers show in your specific league."

## Report Types

| Schedule | Report | Sections |
|----------|--------|----------|
| **Tue-Fri** | Daily Briefing | Roster Intel, Injury Watch, Around the League, Action Items |
| **Monday** | Monday Recap | Last Week's Recap + Daily sections |
| **Saturday** | Weekly Intel | All sections: Roster Intel, Injury Watch, Matchup Preview, Waiver Targets, Trade Signals, Projection Watch, Around the League, Cardinals Corner, Sibling Rivalry, Action Items |

All reports use the same per-player format (metadata table with Sentiment, Lineup, Confidence, Games This Week, Trend) so the structure is consistent regardless of report type.
