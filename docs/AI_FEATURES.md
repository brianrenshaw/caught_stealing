# Lankford Legends — AI Features Guide

A comprehensive guide to all AI-powered features in Lankford Legends, how they connect, and what data feeds into each one.

---

## Architecture Overview

The app uses Claude AI at multiple levels, from a heavyweight daily analysis pipeline to lightweight in-app features. The daily intel reports serve as a knowledge base that enriches the real-time AI features.

```
Expert Content (blogs, podcasts)
        │
        ▼
┌─────────────────────┐
│  Daily Analysis      │  ← Claude Opus 4.6 (3 AM daily)
│  (11 report sections)│
└────────┬────────────┘
         │ sections loaded from disk
         ▼
┌─────────────────────────────────────┐
│  In-App AI Features (on demand)     │
│  ┌───────────┐ ┌─────────────────┐  │
│  │ Analyze   │ │ Weekly Outlook  │  │  ← Claude Sonnet 4
│  │ Lineup    │ │ (narrative)     │  │
│  └───────────┘ └─────────────────┘  │
│  ┌───────────┐ ┌─────────────────┐  │
│  │ Waiver    │ │ Chat Assistant  │  │  ← Claude Sonnet 4
│  │ Analysis  │ │ (11 tools)      │  │
│  └───────────┘ └─────────────────┘  │
└─────────────────────────────────────┘
```

---

## 1. Daily Intelligence Reports

The flagship AI feature — a comprehensive daily briefing powered by Claude Opus that synthesizes expert fantasy baseball content with your league data.

### Model & Configuration
| Setting | Value |
|---------|-------|
| Model | `claude-opus-4-6` |
| Output tokens | 8,000 (daily) / 16,000 (weekly) |
| Schedule | 3 AM daily via `launchd` |
| Script | `scripts/daily_analysis.py` |
| Output | `data/content/analysis/YYYY-MM-DD_*.md` |

### Content Sources

**Blog Articles** (via `scripts/blog_ingest.py`):
- FanGraphs — advanced analytics, prospect coverage, deep dives
- Pitcher List — pitching rankings, streaming analysis, start/sit
- RotoWire — breaking news, injury updates, lineup confirmations

**Podcast Transcripts** (via `scripts/podcast_transcriber.py` + MacWhisper):
- Fantasy Baseball Today (CBS) — daily expert roundtable
- FantasyPros Baseball — consensus rankings, waiver targets
- Locked On Fantasy Baseball — daily deep dives on matchups
- In This League Fantasy Baseball — community-driven analysis

### League Data Injected
- Your full roster with ROS projections, Steamer projections, surplus value, and positional rank
- This week's H2H opponent and their roster
- Brother's team (Ithilien) roster
- Top 50 free agents with projections
- Full league standings (rank, W-L, points for/against)
- Last week's matchup result and player performance
- Weekly game counts per MLB team
- Previous report's player sentiments (for trend tracking)
- FanGraphs player profile URLs

### Report Sections (11 total)

| Section | When | What It Covers |
|---------|------|----------------|
| **Last Week's Recap** | Monday only | League standings table, matchup result, top/bottom 3 performers |
| **My Roster Intel** | Daily | Every rostered player with sentiment table: BULLISH/BEARISH/NEUTRAL, lineup action (START/SIT/SELL/DROP), confidence (HIGH/MED/LOW), games this week, trend arrow (PREVIOUS→CURRENT) |
| **Injury Watch** | Daily | Rostered players with injury concerns; expert context beyond official status |
| **Matchup Preview** | Daily | H2H opponent analysis with position-by-position comparison, edges, vulnerabilities |
| **Waiver Targets** | Daily | Free agents discussed by experts; projection fit, priority flags, closer/setup roles |
| **Trade Signals** | Daily | Sell high from your roster + buy low targets from other teams; expert reasoning |
| **Projection Watch** | Daily | Your players where expert opinion diverges from Steamer consensus |
| **Around the League** | Daily | Major news, trends, prospect call-ups, meta-analysis from expert content |
| **Cardinals Corner** | Daily | STL players across the league; org news; Cardinals fan context |
| **Sibling Rivalry** | Daily | Ithilien team analysis; record, key player sentiments, trade leverage ideas |
| **Action Items** | Daily | Concrete checklist of every recommendation, ordered by urgency |

### Report Schedule
- **Weekdays (Tue–Fri):** Daily briefing — 4 core sections (roster-intel, injury-watch, around-the-league, action-items)
- **Monday:** Expanded daily — adds last-week-recap section
- **Saturday:** Full weekly intel — all 11 sections with comprehensive coverage

### Output Format
- Markdown with YAML frontmatter (`generated_at`, `report_type`, `section_count`, `model`, `input_tokens`, `output_tokens`)
- Split into individual section files for targeted loading
- Obsidian-compatible with TOC directives
- Per-section FanGraphs player linking and source citation linking
- Auto-synced to Fly.io volume after generation

---

## 2. Chat Assistant

An interactive AI assistant accessible via the floating chat bubble on every page.

### Model & Configuration
| Setting | Value |
|---------|-------|
| Model | `claude-sonnet-4-20250514` (configurable) |
| Max tokens | 1,024 per response |
| Daily token limit | 500,000 |
| Conversation history | Last 10 turns |
| Tool-use loop | Up to 5 iterations |

### Available Tools (11)

| Tool | What It Does |
|------|-------------|
| `get_player_stats` | Query batting/pitching stats and Statcast metrics by time period |
| `get_player_projection` | ROS projections with buy/sell signals |
| `get_position_rankings` | Top players at a position by fantasy value |
| `get_matchup_info` | Today's MLB schedule, streaming picks, hitter stacks |
| `get_head_to_head` | Batter vs pitcher matchup context |
| `compare_players` | Side-by-side comparison of 2–5 players |
| `get_waiver_recommendations` | Waiver wire pickup suggestions |
| `get_team_schedule` | MLB team upcoming schedule |
| `evaluate_trade` | Trade evaluation using surplus value methodology |
| `get_player_points` | Fantasy points breakdown using league scoring |
| `get_scoring_config` | League scoring rules reference |

### System Context
- H2H Points keeper league scoring (SV=7, HLD=4, OUT=1.5, ER=-4, K=-0.5)
- 10-team league format
- Conversation history for multi-turn interactions

### Example Queries
- "Who should I pick up this week?"
- "Compare Juan Soto and Aaron Judge"
- "Evaluate trading my Corbin Carroll for their Bobby Witt Jr."
- "Best streaming pitcher today?"

---

## 3. Weekly Lineup Analysis (Analyze Lineup)

AI-powered START/SIT recommendations for the current week, enriched with expert intel.

### Model & Configuration
| Setting | Value |
|---------|-------|
| Model | `claude-sonnet-4-20250514` |
| Max tokens | 1,500 |
| Trigger | "Analyze Lineup" button on dashboard |
| Function | `weekly_lineup_service.analyze_weekly_lineup()` |

### Data Provided to Claude
- Current starters with weekly projected points (4-phase matchup-adjusted)
- Bench players sorted by projected points
- PuLP optimizer swap suggestions (calculated via integer linear programming)
- Two-start pitcher flags
- Multi-position eligibility from Yahoo
- Injury status from MLB Official Injury Report
- League scoring breakdown

### Intel Integration
Loads the most recent versions of these daily analysis sections:
- **roster-intel** — expert sentiments (BULLISH/BEARISH/NEUTRAL) and trend arrows
- **action-items** — actionable checklist with start/sit/add/drop recommendations

Claude is instructed to reference these expert sentiments in its recommendations.

### Output
Markdown with specific START/SIT recommendations, reasoning tied to matchups, schedule, scoring, and expert sentiment.

---

## 4. Weekly Outlook (Narrative Preview Column)

An ESPN/Athletic-style weekly preview column that combines stats with expert analysis.

### Model & Configuration
| Setting | Value |
|---------|-------|
| Model | `claude-sonnet-4-20250514` |
| Max tokens | 2,500 |
| Trigger | "Weekly Outlook" card on dashboard |
| Function | `weekly_lineup_service.generate_weekly_outlook()` |

### Data Provided to Claude
- H2H matchup snapshot with Yahoo vs app projections
- Full league standings with ranks
- Top 10 projected players for both teams
- Hot players trending up
- Buy low / sell high candidates
- 15 most relevant injuries
- Full week game schedule with weather and park factors
- Ithilien (brother's team) roster and standing
- Cardinals Corner data (STL players on relevant rosters)
- League scoring rules

### Intel Integration
Loads the most recent versions of these daily analysis sections:
- **matchup-preview** — expert narrative analysis of the H2H matchup
- **roster-intel** — player sentiments and trends
- **projection-watch** — where expert opinion diverges from Steamer
- **trade-intel** — sell high / buy low reasoning
- **action-items** — current action checklist

Claude weaves these insights into the narrative, citing expert opinions.

### Output Sections
1. H2H matchup storyline — edges and vulnerabilities
2. Projection analysis — Yahoo vs App discrepancies
3. Key players to watch on both sides
4. Schedule and weather factors
5. Injury concerns for both rosters
6. League standings context and playoff positioning
7. Cardinals Corner — STL players in the matchup
8. Ithilien Watch — brother's team update

---

## 5. Waiver Wire AI Analysis

Personalized waiver pickup/drop recommendations based on your roster's weak spots.

### Model & Configuration
| Setting | Value |
|---------|-------|
| Model | `claude-sonnet-4-20250514` |
| Max tokens | ~1,500 |
| Trigger | "AI Waiver Analysis" button on Waivers page |
| Function | `waiver_service.analyze_roster_waivers()` |

### Data Provided to Claude
- Current roster with ROS projections and efficiency rates (points/PA, points/IP)
- Identified weak spots (positions below average)
- Top 15 waiver targets with composite scores
- Two-start pitchers (in weekly mode)
- Closer vacancies (injured closers, available setup men)
- Statcast breakout candidates
- Relevant injuries
- Platoon splits (vs LHP/RHP) for top 5 waiver picks
- League scoring breakdown with emphasis on SV=7, HLD=4 reliever premium

### Output
Markdown with specific pickup suggestions, role context for relievers, injury-related opportunities, and split-based analysis.

---

## 6. Content Ingestion Pipeline

The foundation that feeds the daily analysis — automated collection of expert fantasy baseball content.

### Components

| Script | What It Does | Schedule |
|--------|-------------|----------|
| `scripts/blog_ingest.py` | Fetches RSS feeds from 3 sites → markdown with frontmatter | 3 AM daily |
| `scripts/podcast_transcriber.py` | Downloads podcast episodes → MacWhisper watch folder | 3 AM daily |
| `scripts/transcript_collector.py` | Collects MacWhisper output → formatted markdown | 3 AM daily |
| `scripts/daily_analysis.py` | Claude Opus generates report from all content + league data | 3 AM daily |
| `scripts/daily_content_ingest.sh` | Orchestrates all steps + syncs reports to Fly.io | 3 AM via launchd |

### Content Flow
```
RSS Feeds ──► blog_ingest.py ──► data/content/blogs/*.md
                                         │
Podcast Feeds ──► podcast_transcriber.py  │
                    │                     │
                    ▼                     │
              MacWhisper                  │
                    │                     │
                    ▼                     │
          transcript_collector.py         │
                    │                     │
                    ▼                     ▼
              data/content/        daily_analysis.py
              transcripts/*.md ──►    (Claude Opus)
                                         │
                                         ▼
                                  data/content/analysis/*.md
                                         │
                                         ▼
                                  flyctl sftp → Fly.io volume
```

### Storage Locations
| Path | Contents |
|------|----------|
| `data/content/blogs/` | Markdown articles from RSS feeds |
| `data/content/transcripts/` | Formatted podcast transcripts |
| `data/content/audio/pending/` | MP3s waiting for MacWhisper |
| `data/content/audio/transcribed/` | MacWhisper text output |
| `data/content/analysis/` | Daily/weekly intel reports |
| `data/content/manifest.json` | Index of all ingested content |

---

## 7. How Intel Feeds Into Real-Time Features

The daily analysis creates a knowledge base that the real-time AI features draw from. This means the lineup analysis and weekly outlook don't just use raw stats — they incorporate expert opinions, sentiment trends, and contextual analysis from the morning's content pipeline.

### Intel Loading Mechanism
The `_load_latest_intel()` function in `weekly_lineup_service.py`:
1. Scans `data/content/analysis/` for the most recent file matching each section type
2. Reads markdown content (strips YAML frontmatter)
3. Truncates to 4,000 characters per section to stay within token budget
4. Returns gracefully empty dict if no files found

### Injection Map

| Feature | Intel Sections Used |
|---------|-------------------|
| Analyze Lineup | `roster-intel`, `action-items` |
| Weekly Outlook | `matchup-preview`, `roster-intel`, `projection-watch`, `trade-intel`, `action-items` |
| Chat Assistant | None (uses live tool calls instead) |
| Waiver Analysis | None (uses live data queries) |

### Token Budget
Each intel section is capped at 4,000 characters (~1,000 tokens). With 2 sections for lineup analysis and 5 for weekly outlook, the total intel injection adds roughly 2,000–5,000 tokens to each prompt — well within Sonnet's context window.

---

## API Keys & Configuration

All AI features require the `ANTHROPIC_API_KEY` environment variable. Configuration in `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
ASSISTANT_MODEL=claude-sonnet-4-20250514   # For in-app features
ASSISTANT_MAX_TOKENS=1024                   # Chat assistant response limit
ASSISTANT_DAILY_TOKEN_LIMIT=500000          # Daily chat budget
```

The daily analysis script uses `claude-opus-4-6` directly (hardcoded for quality).

---

## Cost Estimates

| Feature | Model | Typical Usage | Estimated Cost |
|---------|-------|--------------|----------------|
| Daily Intel | Opus 4.6 | 1 report/day, ~525K input + 7K output tokens | ~$2.80/day |
| Chat Assistant | Sonnet 4 | Varies by usage | ~$0.01–0.10/query |
| Analyze Lineup | Sonnet 4 | 1-2x/week | ~$0.02/use |
| Weekly Outlook | Sonnet 4 | 1x/week | ~$0.03/use |
| Waiver Analysis | Sonnet 4 | 1-2x/week | ~$0.02/use |
| **Monthly total** | | | **~$85–90/month** (mostly daily intel) |
