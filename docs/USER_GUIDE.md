# Fantasy Baseball Analysis App — User Guide

A data-driven fantasy baseball analysis tool that connects to your Yahoo Fantasy league and combines real MLB data from FanGraphs and Statcast to help you make smarter roster decisions. Whether you're evaluating a trade, scanning the waiver wire, or setting your weekly lineup, this app turns raw numbers into actionable insights.

---

## Table of Contents

- [Getting Started](#getting-started)
  - [First Launch](#first-launch)
  - [Syncing Data](#syncing-data)
  - [Navigation](#navigation)
- [App Pages](#app-pages)
  - [Dashboard](#dashboard)
  - [Roster](#roster)
  - [Trade Analyzer](#trade-analyzer)
  - [Waivers](#waivers)
  - [Stats Explorer](#stats-explorer)
  - [Projections](#projections)
  - [Projection Comparison](#projection-comparison)
  - [Player Detail Page](#player-detail-page)
  - [Matchups](#matchups)
  - [Compare Players](#compare-players)
  - [Player Popup (Quick Look)](#player-popup-quick-look)
  - [Intel](#intel)
  - [Chat Assistant](#chat-assistant)
- [Understanding the Stats](#understanding-the-stats)
  - [Batting Stats — The Basics](#batting-stats--the-basics)
  - [Batting Stats — Advanced](#batting-stats--advanced)
  - [Pitching Stats — The Basics](#pitching-stats--the-basics)
  - [Pitching Stats — Advanced](#pitching-stats--advanced)
  - [Statcast Metrics](#statcast-metrics)
- [Key Concepts](#key-concepts)
  - [Buy Low / Sell High Signals](#buy-low--sell-high-signals)
  - [Projection Blending (Consensus Projections)](#projection-blending-consensus-projections)
  - [Confidence Scores](#confidence-scores)
  - [Z-Scores and Trade Values](#z-scores-and-trade-values)
  - [VORP and Surplus Value](#vorp-and-surplus-value)
  - [Waiver Wire Scoring](#waiver-wire-scoring)
  - [Streaming and Stacking](#streaming-and-stacking)
- [Glossary](#glossary)
- [Tips for Getting the Most Out of This App](#tips-for-getting-the-most-out-of-this-app)
- [Backtesting & Analysis Tools](#backtesting--analysis-tools)
  - [Running the Data Pipeline](#running-the-data-pipeline)
  - [Running the Backtest](#running-the-backtest)
  - [Analysis Reports](#analysis-reports)
  - [Parameter Optimization](#parameter-optimization)
  - [Understanding the Results](#understanding-the-results)

---

## Getting Started

### First Launch

When you first open the app, you'll see the **Dashboard** with empty sections. There are two paths to get started:

1. **Sync Stats** (no Yahoo account needed) — Click the "Sync Stats" button to pull batting, pitching, and Statcast data from FanGraphs and Baseball Savant for the current MLB season. This populates the Stats Explorer, Projections, and Trade Analyzer with real data for every qualified MLB player.

2. **Connect Yahoo Fantasy** — If you have a Yahoo Fantasy Baseball league, configure your Yahoo API credentials in the `.env` file and click "Sync Yahoo" to pull your league's standings, rosters, and team-level stats. This enables the Roster page, league standings, and personalized recommendations.

You can use the app with just public stats data (path 1) or with both sources combined for the full experience.

### Syncing Data

The Dashboard has three sync controls:

- **Sync Yahoo** — Pulls league standings, all team rosters, and player stats from your Yahoo Fantasy league. Requires Yahoo API credentials to be configured.

- **Sync Stats** — Pulls the current season's FanGraphs batting and pitching leaderboards plus Statcast data (exit velocity, barrel rate, expected stats) for all qualified MLB players.

- **Multi-Season Sync** — Click the dropdown arrow next to "Sync Stats" to reveal checkboxes for seasons 2015–2025. Select multiple years and sync them all at once to build a historical database for trend analysis.

After syncing, a stats summary bar appears at the bottom of the Dashboard showing how many batters, pitchers, and Statcast records are loaded, along with the timestamp of the last sync.

Syncs can take a minute or two depending on how much data is being pulled. There is a 5-minute cooldown between syncs to avoid overloading the data sources. The app also runs automated syncs in the background: Yahoo data refreshes every 6 hours, and stats refresh daily at 5:00 AM ET.

### Navigation

- **Sidebar** (left side): Links to all major pages — Dashboard, Roster, Trades, Waivers, Stats Explorer, Projections, Matchups, and Intel.
- **Player Search** (top of sidebar): Type any player name to search across the entire database. Results appear as a dropdown — click a name to open their full Player Detail page.
- **Chat Assistant** (bottom-right corner): A blue chat bubble that opens an AI-powered analysis panel. Ask questions about your roster, get trade advice, or request player comparisons.

---

## App Pages

### Dashboard

**What it shows:**

The Dashboard is your home base — a snapshot of your league and the broader baseball landscape.

| Section | Description |
|---------|-------------|
| **Weekly Outlook** | AI-generated professional analysis column (ESPN/Athletic style). Covers H2H matchup storyline with dual projections (Yahoo vs app), key players with fantasy team tags, schedule/weather, injuries, standings, Cardinals Corner, and Ithilien Watch. Rendered as rich markdown with **Copy** (clipboard as rich text) and **Email** (copies + opens mail client) buttons. |
| **Weekly Matchup Analysis** | Full-width card showing your current H2H matchup. Displays projected and actual points for both teams, plus a category-by-category breakdown showing raw stats and points for every scoring category (batting: R, 1B, 2B, 3B, HR, RBI, SB, CS, BB, HBP, K; pitching: OUT, K, SV, HLD, RW, QS, etc.). Projected points freeze at the start of each week; actual points update with every Yahoo sync. Green = you lead, red = opponent leads. |
| **League Standings** | Your league's current standings table: rank, team name, W-L-T record, and Points For. Your team is highlighted. |
| **Weekly Lineup** | Your roster with projected fantasy points for the current week, powered by consensus rate stats (Steamer + ZiPS + ATC average) adjusted through 4-phase matchup modeling (opposing pitcher quality, opponent offense, park factors, platoon splits). Shows team games, two-start pitcher badges (2S), and injury flags (DTD/IL). The optimizer bar suggests specific START/BENCH swaps to maximize weekly points. Bench players shown in a collapsible section. Click "Analyze Lineup" for AI-powered start/sit recommendations. Falls back to ROS actual/projected view when weekly data is unavailable. |
| **Buy Low / Sell High Signals** | Cards highlighting players whose expected performance (xwOBA) significantly differs from their actual results (wOBA). These are trade opportunity alerts. |
| **Category Leaders** | A 4-column grid showing the top players in HR, SB, AVG, and K — the marquee fantasy categories. |
| **Top Hitters** | A sortable, filterable table of the best hitters. Columns: PA, HR, R, RBI, SB, AVG, OBP, SLG, OPS, wOBA, wRC+. Click any column header to sort. |
| **Top Pitchers** | Same format for pitchers. Columns: IP, W, L, SV, K, ERA, WHIP, K/9, BB/9, FIP. |
| **Season Selector** | Dropdown to switch between any season you've synced data for. |

**Interactive features:** Click any column header in the hitter/pitcher tables to sort ascending or descending (arrows indicate direction). Use the search/filter box above each table to quickly find a player. All player names are clickable.

**How the matchup analysis works:**

The matchup card shows three projection rows side by side:

| Row | Source | What It Means | When It Updates |
|-----|--------|---------------|-----------------|
| **Yahoo Projected** | Yahoo Fantasy API | Yahoo's own weekly projection. Uses Yahoo's internal models and schedule data. | Frozen when matchup first loads each week. |
| **My Projected** | Custom matchup-adjusted model | Four-layer model using FanGraphs rates, MLB schedule, opponent quality, park factors, and platoon splits. See detailed methodology below. | Frozen when matchup first loads each week. |
| **Actual** | Yahoo weekly stats | Real points scored so far this week from Yahoo's live scoring. | Updates every time you click "Sync Yahoo." |

Below the summary, each team's full roster is shown player-by-player with per-category stats. Each player shows their fantasy roster position (C, 1B, SP, RP, BN, IL, etc.). Active players show projected and actual stats; bench/IL players are dimmed with zero projections. Each category column has **P** (projected) and **A** (actual). A totals row sums each column.

#### My Projected — Detailed Methodology

The "My Projected" model uses consensus rate stats (averaged from Steamer, ZiPS, and ATC) as its base, then applies a four-layer approach to generate matchup-aware weekly projections. All methodology choices are sourced from FanGraphs research and Tom Tango's *The Book*.

**Base Volume (Schedule-Aware):**

| Player Type | Volume Estimation |
|-------------|-------------------|
| Hitters | `(season PA / 162) × team regular-season games this week` — uses actual game count from MLB API, filters out spring training |
| Starting Pitchers | `IP/start × probable starts` (from MLB probable pitcher API). Falls back to `(season IP / 162) × team games` when probables aren't posted. |
| Relievers | `(season IP / G) × (G / 162) × team games` — uses actual appearance rate (e.g., a closer appearing in 43% of team games), not a flat estimate |

**Layer 1: Opposing Pitcher Quality (Hitter Adjustment)**

For each game a hitter plays, the opposing probable starter's quality adjusts the projection:

| Stat Category | Metric Used | Why This Metric |
|---------------|-------------|-----------------|
| R, H, 1B, 2B, 3B, HR, RBI, HBP | SIERA ratio vs league avg (~4.15) | SIERA is park-adjusted (confirmed by FanGraphs: *"SIERA is park-adjusted"*). Avoids double-counting with park factors. |
| K | Pitcher's actual K% vs league avg (~22%) | K% is a pitcher-specific skill that varies independently of SIERA. Two pitchers with identical SIERA can have very different K rates. |
| BB | Pitcher's actual BB% vs league avg (~8%) | Same reasoning — BB% is pitcher-controlled. |
| SB, CS | No adjustment | Pitcher quality doesn't affect base-stealing. |

All ratios are **dampened by 50%** (apply half the raw effect) and clamped to [0.80, 1.20]. Dampening is a modeling choice — single-game outcomes are dominated by randomness, so the full opponent ratio would overstate the effect. Games without a named probable starter use neutral (1.0) multipliers.

**Layer 2: Opposing Team Offense (Pitcher Adjustment)**

For each pitcher's start or appearance, the opposing team's offensive quality adjusts H and ER projections:

| Stat | Metric | Dampening | Clamp |
|------|--------|-----------|-------|
| H allowed | Team wRC+ / 100 | 35% | [0.90, 1.15] |
| ER allowed | Team wRC+ / 100 | 35% | [0.90, 1.15] |
| K, BB | No adjustment | — | — |

**Why wRC+**: It's park AND league adjusted (confirmed by FanGraphs). Using raw team AVG or wOBA with park factors would double-count park effects. **Why heavier dampening (35% vs 50%)**: wRC+ has weaker predictive validity (~0.3-0.4 correlation) for individual pitcher-vs-lineup matchups than SIERA does for pitcher quality (~0.7). **Why no K/BB adjustment**: Both are ~75-80% pitcher-controlled.

**Layer 3: Park Factors**

Each game's venue affects run-environment stats:

1. **Neutralize**: Raw season stats include ~50% home park influence. Divide by `home_blend = 0.5 × home_park_factor + 0.5 × 1.0` to get park-neutral rates.
2. **Apply venue**: Multiply by the average park factor of this week's actual game venues.
3. **Result**: A Rockies hitter playing 3 away games at Oracle Park gets both the Coors inflation removed AND the Oracle Park suppression applied.

Park factors apply to R, H, HR, 2B, 3B, RBI (hitters) and H, ER (pitchers). They do NOT apply to BB, K, SB, or CS (park-independent). Park factor data from FanGraphs 5-year regressed factors (Coors Field: 1.38, Oracle Park: 0.92, etc.).

**Why full strength per game**: FanGraphs halves park factors for season-long stats because players split time home/away. But for per-game projections at a specific venue, the full factor is correct.

**Layer 4: Platoon Splits (LHP/RHP)**

When the opposing starter's handedness is known (from MLB Stats API), hitter projections use regressed platoon split rates instead of overall rates:

1. Fetch the hitter's vs-LHP or vs-RHP split from the `player_splits` table (from Baseball Reference via pybaseball)
2. **Regress toward league average** per Tom Tango's *The Book*:
   - Right-handed hitters: regress toward **2,200 PA** of league-average split performance
   - Left-handed hitters: regress toward **1,000 PA**
   - Formula: `regressed = (observed × PA + league_avg × regression_PA) / (PA + regression_PA)`
3. Compute per-stat ratios (wOBA, ISO, AVG, K%, BB%) vs overall rates
4. **Replaces** Layer 1 for that game (since splits already capture the pitcher-type effect)
5. Falls back to Layer 1 if split data unavailable or sample < 50 PA

**Why regression is critical**: With only 200 PA vs LHP, the observed split is mostly noise. A RHH's observed vs-LHP wOBA carries only ~8% weight vs league average (200 / (200 + 2200)). This prevents overreacting to small-sample flukes.

#### Double-Counting Prevention

Every metric was chosen to avoid double-counting with park factors:

| Metric | Park-Adjusted? | Source |
|--------|---------------|--------|
| SIERA | **Yes** | FanGraphs: *"SIERA is park-adjusted"* |
| FIP, xFIP | No | FanGraphs: *"FIP is not league or park adjusted"* |
| wRC+ | **Yes** | FanGraphs: park and league adjusted |
| wOBA, AVG, ISO | No | Raw stats — park factors applied separately |
| xwOBA, xBA, xERA | No | Statcast expected stats (not used in weekly matchup projections) |

Raw counting stats (H, HR, R, etc.) from FanGraphs are NOT park-adjusted → applying park factors in Layer 3 is correct. SIERA (Layer 1) and wRC+ (Layer 2) are park-adjusted → they don't overlap with Layer 3.

**Starting Lineup:** Shows your active roster players (all positions except BN, IL, NA) with their full-season actual points earned and projected ROS points. BN and IL players are shown dimmed. Use this to quickly spot which starters are producing and which are underperforming.

**Why it matters for fantasy:** The matchup breakdown shows exactly which scoring categories are driving the point differential — so you know if you're losing because of a pitching collapse (ER at -4 pts each) or winning because your hitters are racking up HR (4 pts each). Comparing Yahoo's projection to your custom projection can reveal when Yahoo is over- or under-valuing your roster based on matchup context.

---

### Roster

**What it shows:**

Two tables displaying your Yahoo Fantasy roster:

- **Batters** — Grouped by roster position (C, 1B, 2B, 3B, SS, OF, UTIL, BN). Each row shows the player's name, MLB team, eligible positions, and their current stats. Stat columns populate dynamically based on what data is available.
- **Pitchers** — Grouped by SP and RP slots, with the same dynamic stat columns.

Every player name is clickable, opening either the Player Popup or the full Player Detail page.

**Why it matters for fantasy:** This is your roster at a glance. It mirrors your Yahoo lineup so you can see your current starters, bench players, and their stats without switching to Yahoo. Use it to quickly identify underperformers who might need to be benched or dropped.

> **Note:** This page requires a Yahoo sync to populate. Without Yahoo credentials, it will be empty.

---

### Trade Analyzer

**What it shows:**

All trade analysis is powered by the league's H2H Points scoring system (SV=7, HLD=4, OUT=1.5, ER=-4, K=-0.5). Every value on this page is expressed in projected fantasy points, not generic z-scores.

Two sections:

1. **Evaluate a Trade** — Search and add players to Side A and Side B, then click "Analyze Trade." The app returns:
   - **Surplus value** for each player — their projected rest-of-season points above a replacement-level player at the same position
   - **Projected points** for each player — estimated total ROS fantasy points in this scoring format
   - **Total surplus** for each side and the **value difference** between them
   - A **fairness rating**: Fair (< 20 pts), Slightly Favors (20–75 pts), or Heavily Favors (> 75 pts)
   - **League-specific analysis** explaining why the trade is good or bad in this format — it highlights reliever premium (SV=7 means closers are irreplaceable), innings value (IP=4.5 pts from outs), and translates the point gap into tangible equivalents ("equivalent to ~5 saves or ~11 extra innings pitched")

2. **Trade Value Rankings** — All players ranked by surplus value, showing:
   - **Pos Rank** — Their rank among players at the same position (e.g., SS #3)
   - **Proj Pts** — Projected rest-of-season fantasy points in your scoring system
   - **Surplus** — Points above replacement at their position. This is the number that matters for trades — a positive surplus means the player produces more points than what you could freely acquire on waivers

**Why it matters for your league:** In H2H Points with SV=7 and ER=-4, traditional fantasy rankings can be wildly misleading. A closer with 35 saves generates 245 points from saves alone — that's comparable to an entire season from a decent hitter. An innings-eating starter averaging 6.5 IP/start collects 29 points per outing just from outs. Meanwhile, a power hitter with 35 HR but 170 strikeouts loses 85 points to Ks. The surplus value on this page accounts for all of this, so you can evaluate trades with confidence that the numbers reflect your actual league. Don't trade your closer for a middling bat just because ESPN says the hitter is ranked higher — in this format, the closer might genuinely be more valuable. See [Fantasy Points and Surplus Value](#fantasy-points-and-surplus-value) for the full methodology.

#### Triple Projection Columns

The trade analyzer shows three projection columns for every player:

| Column | Source | What It Tells You |
|--------|--------|-------------------|
| **Consensus Projected** | Average of Steamer + ZiPS + ATC rest-of-season projections, converted to league fantasy points | The primary valuation — averaging three independent systems is more accurate than any single one. This is the same projection base used by waivers and the optimizer. |
| **App Projected** | Custom blend of actual stats and Statcast expected metrics, weighted toward recent performance | Supplementary estimate that accounts for quality-of-contact regression and recent trends |
| **Actual Points** | Fantasy points actually scored this season using league scoring rules | What the player has actually produced — compare to projections to spot over/underperformers |

**Reading disagreements between columns:**
- **Consensus >> Actual**: The player is underperforming professional projections — buy low candidate
- **Actual >> Consensus**: The player is outperforming projections — sell high candidate or genuine breakout
- **App Projected >> Consensus**: Recent Statcast improvements suggest the player is better than their historical track record
- **Consensus >> App Projected**: The consensus sees long-term value that recent trends don't reflect

#### AI Trade Suggestions

Click **Find Trade Opportunities** to have Claude AI scan every opponent's roster against your team. The analysis:
- Identifies your team's weakest positions and stat categories
- Searches all opponents for players who fill those gaps
- Evaluates trade feasibility using surplus values from all three projection systems
- Suggests **aggressive** trades (higher upside, opponent may hesitate) and **conservative** trades (more likely to be accepted)
- Names specific players on both sides with point values
- Recommends standing pat if no available trade improves your team

#### AI Trade Analysis

After evaluating a specific trade, click **Get AI Analysis** for a narrative breakdown that explains:
- How the trade affects your roster construction and positional depth
- Where the three projection systems agree or disagree on the players involved
- Relevant Statcast trends (exit velocity changes, barrel rate shifts, pitch mix evolution)
- Current injury status and return timelines
- Whether the trade makes sense given your league's scoring rules and your current standings position

---

### Waivers

**What it shows:**

A ranked table of waiver wire recommendations scored from 0 to 100, specifically tuned for your H2H Points league. Use the **Projection Period dropdown** to switch between full-season (ROS) and weekly views.

#### Projection Period Dropdown

| Period | Description |
|--------|-------------|
| **Full Season (ROS)** | Ranks players by rest-of-season projected fantasy points. Best for long-term roster building. |
| **This Week** | Ranks by projected points for the current Mon–Sun period. Factors in team schedule, two-start pitchers, reliever opportunities, and matchup quality. Excludes IL players; penalizes DTD players. |
| **Next Week** | Same as This Week but for the following Mon–Sun period. Useful for planning ahead before Monday's waiver deadline. |

#### Table Columns

| Column | Description |
|--------|-------------|
| **Player** | Name, team, and position. May include badges: **2-START** (green, pitcher has two starts this week), **CLOSER OPP** (emerald, setup man on a team whose closer is injured), **BREAKOUT** (orange, Statcast metrics surging). |
| **Pos** | Primary position. Relievers also show a role badge: **CL** (closer, green), **SU** (setup, blue), **MR** (middle), **LR** (long). |
| **Score** | Composite waiver score (0–100), weighted: projected points (35%), trend (25%), position scarcity (15%), scoring fit (15%), schedule volume (10%). |
| **Week Pts** | (Weekly view only) Projected fantasy points for the selected week (rate × games). |
| **Consensus** | (ROS view) Consensus projection from averaging Steamer, ZiPS, and ATC rest-of-season projections. The same projection base used by trades and the optimizer, ensuring consistent valuations. |
| **My Proj** | (ROS view) App projection: actual counting stats scaled to remaining games. Comparing Consensus vs My Proj reveals over/under-performers — disagreements highlight where recent performance diverges from professional projections. |
| **Rate** | Points per plate appearance (hitters) or per inning pitched (pitchers). |
| **Games** | (Weekly only) Number of team games that week, with pitcher starts shown as "(2S)". |
| **Fit** | League scoring fit (50=neutral, 75+=premium). Boosted for two-start pitchers (+20) and closer vacancy pickups (+25). |
| **Trend** | **HOT** / **COLD** / **--** based on last-14 vs full-season Statcast xwOBA delta. |
| **Status** | **BUY LOW** (xwOBA >> wOBA), **DTD** (day-to-day, yellow), **IL** (injured list, red). Injury tooltips show specific injury and source (MLB Official Injury Report). |
| **Reasoning** | League-specific explanation with point values, matchup context, and injury flags. |

#### AI Roster Analysis

Click **Analyze My Roster** to get personalized pickup/drop recommendations from Claude AI. The analysis considers:
- Your current roster by position with stats and weak spots
- Top waiver targets with scores and projections
- Current injury report (Source: MLB Official Injury Report)
- Two-start pitchers and closer vacancies
- Statcast breakout candidates
- League scoring rules

For weekly analysis, the AI specifically avoids recommending DTD/IL players and prioritizes schedule-favorable pickups.

#### Key Features for Weekly Pickups

- **Two-start pitchers**: SPs with two starts in the selected week get a "2-START" badge and a +20 scoring fit bonus. In a league where each IP = 4.5 base points, a second start adds 20-30+ raw points.
- **Closer vacancy detection**: When a team's closer hits the IL, their setup man is flagged with "CLOSER OPP" — the highest-value weekly waiver pickup possible (SV = 7 points each).
- **Reliever role context**: Role badges (CL/SU/MR/LR) with projected save/hold opportunities and point estimates from those opportunities.
- **Statcast breakout detection**: Players meeting 2+ of these criteria get a "BREAKOUT" badge: barrel% up 3+%, hard-hit% up 5+%, or xwOBA up .030+ (last 14 days vs full season).
- **Injury-aware filtering**: IL players are excluded from weekly views entirely. DTD players show a warning and have their weekly projection reduced by 50%.

**Why it matters for your league:** In most fantasy formats, the waiver wire is about finding the next breakout hitter. In H2H Points with these scoring rules, the waiver wire is also about:

- **Reliever hunting**: A closer sitting on waivers who gets 3 saves this week just produced 21 points from a single roster slot. Setup men with holds are worth 4 points per hold. The Fit column highlights these players.
- **Contact hitter arbitrage**: A .275 hitter with 12% K rate is quietly producing more fantasy points per plate appearance than a .250 hitter with 30 HR and 28% K rate. The Pts/PA column reveals this, and these players often sit unclaimed because their traditional stats look boring.
- **Streaming starters carefully**: In this format, a bad streaming start is catastrophic. A 5-ER outing costs -20 points from earned runs alone and can easily be net-negative for the whole start. The Week/Proj Pts column helps you only grab starters who are genuinely projected to produce positive value.
- **Schedule exploitation**: Teams playing 7 games in a week give their hitters ~30% more PA than teams playing 5 games. The weekly view surfaces this automatically.

See [Waiver Wire Scoring](#waiver-wire-scoring) for the full formula breakdown.

---

### Stats Explorer

**What it shows:**

An interactive charting dashboard with three tabbed views, each featuring Plotly charts you can hover over, zoom into, and click on:

#### Statcast Tab
- **Exit Velocity vs Barrel Rate** scatter plot — Each dot is a player, color-coded by xwOBA. Players in the upper-right corner hit the ball hard AND frequently barrel it up — these are the best hitters in baseball.
- **xwOBA vs Actual wOBA** scatter ("the luck chart") — Compares expected performance (xwOBA, based on batted ball quality) to actual results (wOBA). Players above the diagonal are underperforming their batted ball quality and likely to improve (buy low); players below are overperforming (sell high).
- **xwOBA Distribution** histogram — Shows the spread of expected performance across all players. A player's position on this curve tells you how they compare to the field.

#### Batting Tab
- **wRC+ Leaders** bar chart — Horizontal bars ranking the best hitters by wRC+ (Weighted Runs Created Plus). A reference line at 100 marks league average.
- **K% vs BB%** scatter ("plate discipline chart") — Lower-left is the best spot (low strikeouts, high walks). Upper-right means a player swings and misses a lot while rarely walking — a red flag.
- **wOBA Distribution** histogram — Shows the spread of actual offensive performance.

#### Pitching Tab
- **FIP vs ERA** scatter — Points below the diagonal line have an ERA higher than their FIP, suggesting they've been unlucky and may improve. Points above the line may regress.
- **K-BB% Leaders** bar chart — The gap between strikeout rate and walk rate. Bigger gap = more dominant pitcher.
- **ERA Distribution** histogram — Visualizes the range of ERA across all qualified pitchers.

**Interactive features:** Season selector dropdown, minimum PA filter (default 50), hover tooltips showing player name and exact values, and tab switching. Use the **Highlight player** search box to find a specific player — selecting them marks their position on all charts in the current tab with a red diamond and label (scatter plots) or red bar highlight (bar charts), plus a vertical line on distribution histograms. Click "x Clear" to remove the highlight. Chart data points for players on your roster appear as gold stars; other rostered players are blue circles; free agents are green X marks. Click any data point to navigate to that player's detail page.

**Why it matters for fantasy:** Charts reveal patterns that tables can't. The FIP vs ERA scatter instantly shows you which pitchers are due for regression. The K% vs BB% plot highlights hitters with elite plate discipline (a strong predictor of sustained success). The Statcast charts bypass traditional stats entirely, showing you which players are making the best contact regardless of their batting average.

---

### Projections

**What it shows:**

Rest-of-season projections for all qualified players, generated by the app's [consensus projection engine](#projection-blending-consensus-projections) (averaging Steamer, ZiPS, and ATC from FanGraphs).

- **Hitter/Pitcher Toggle** — Switch between hitter and pitcher projection views.
- **Position Filter Pills** — For hitters: All, C, 1B, 2B, 3B, SS, OF, DH. For pitchers: All, SP, RP.
- **Season Selector** — View projections based on any synced season's data.

**Hitter Projection Table:**

| Column | Description |
|--------|-------------|
| HR, R, RBI, SB | Projected rest-of-season counting stats |
| AVG, OPS | Projected rate stats |
| Adj FP | Analytics-adjusted fantasy points — adjusts baseline projection using xwOBA vs wOBA divergence. Green ▲ = underperforming contact quality (expect improvement). Red ▼ = overperforming (expect regression). |
| Signal | **BUY** (green) or **SELL** (red) badge when xwOBA gap exceeds ±.030 |
| xwOBA Delta | The gap between expected and actual performance |
| Confidence | Visual bar showing how reliable the projection is (see [Confidence Scores](#confidence-scores)) |

Click **Show Advanced** to reveal additional analytics columns:

| Column | What It Measures | Why It Matters |
|--------|-----------------|----------------|
| xwOBA | Expected wOBA from Statcast contact quality | Primary buy/sell indicator — compares to actual wOBA |
| wOBA | Actual weighted on-base average | Baseline offensive production measure |
| ISO | Isolated power (SLG minus AVG) | Extra-base hit production — scores 2x-4x singles |
| Barrel% | Optimal exit velocity + launch angle rate | Leading indicator for HR and XBH power |
| HardHit% | 95+ mph exit velocity rate | Early-season contact quality signal |
| BB% | Walk rate | Each walk = +1 pt in this scoring |
| K% | Strikeout rate (green if <18%, red if >25%) | Each K = -0.5 pts — low-K hitters have a hidden edge |
| Spd | Sprint speed in ft/s | Drives stolen base projection |
| SB% | Stolen base success rate | Net SB value at 2/-1 scoring |
| BABIP | Batting average on balls in play | Luck indicator — compare to career norm |

**Pitcher Projection Table:**

| Column | Description |
|--------|-------------|
| W, SV, K | Projected rest-of-season counting stats |
| ERA, WHIP | Projected rate stats |
| Adj FP | Analytics-adjusted fantasy points — adjusts using xERA/SIERA vs ERA divergence. Green ▲ = better than results show. Red ▼ = regression risk. |
| Signal | BUY/SELL badge |
| Confidence | Reliability indicator |

Click **Show Advanced** to reveal pitcher analytics:

| Column | What It Measures | Why It Matters |
|--------|-----------------|----------------|
| xERA | Expected ERA from Statcast | Best buy/sell signal for pitchers |
| SIERA | Skill-interactive ERA | Most reliable future ERA predictor |
| K% | Strikeout rate (green >25%) | Each K = +0.5 pts AND prevents hits |
| BB% | Walk rate (red >10%) | Each BB = -0.75 pts, often leads to ER |
| K-BB% | Single best composite pitching skill number | Green >18%, red <10% |
| GB% | Ground ball rate (green >50%) | Reduces HR and ER exposure |
| HR/FB% | HR per fly ball — regression indicator | <8% = lucky, >15% = unlucky |
| Whiff% | Swinging strike rate (green >30%) | Fastest-stabilizing K predictor |
| gmLI | Game leverage index | >1.5 = high-leverage reliever (closer-in-waiting) |
| IP/G | Innings per appearance | Multi-inning relievers earn more volume points |

Below the main table, two side-by-side panels show:
- **Buy Low Candidates** — Players whose xwOBA exceeds their actual wOBA (they're underperforming their contact quality and likely to improve)
- **Sell High Candidates** — Players whose actual wOBA exceeds their xwOBA (they're overperforming and likely to regress)

Each panel shows the player's actual wOBA, xwOBA, and the gap between them.

**Why it matters for fantasy:** Projections are the foundation of every good fantasy decision. Should you start Player A or Player B? Who will produce more HR rest-of-season? This page answers those questions using a blend of traditional stats, recent performance, and Statcast expected stats — not just one data source. The Adj FP column is the most actionable metric — it tells you whether a player's projected points should be adjusted up or down based on contact quality analytics. The Buy Low / Sell High panels are especially powerful early in the season when small samples create misleading batting averages but Statcast data already tells the real story.

---

### Projection Comparison

**What it shows:**

A side-by-side comparison tool for up to 4 players at once. Search and select players to compare, then see:

- **Comparison Table** — Blended projection stats for each player in adjacent columns. For hitters: HR, R, RBI, SB, AVG, OBP, OPS. For pitchers: W, SV, K, ERA, WHIP.
- **Radar Chart** — A spider/polar chart that normalizes each stat to a 0–100 scale so you can visually compare player profiles. For pitchers, ERA and WHIP are inverted (lower actual value = further from center = better).

Players can be added or removed dynamically.

**Why it matters for fantasy:** When you're debating between two trade targets or deciding which free agent to pick up, raw stat tables can be hard to compare. The radar chart instantly shows you which player has a more balanced profile vs. one who is elite in one category but weak in others. For example, a player with elite SB but low HR will have a very different radar shape than a balanced contributor — both are valuable, but in different roster contexts.

---

### Player Detail Page

**What it shows:**

The most comprehensive view of any single player. Access it by clicking a player name link anywhere in the app.

**Header Section:**
- Player name, MLB team, and primary position
- **Roster Status Badge** — "My Team" (green), another fantasy team's name (gray), or "Free Agent" (blue)
- **Trade Value Badge** — The player's surplus value and positional rank
- **Buy Low / Sell High Banner** — When applicable, shows the composite gap score and individual breakdowns (xwOBA gap, xBA gap, FIP-ERA gap for pitchers)

**Five Tabs:**

#### 1. Standard Stats
Batting or pitching stats across four time windows:
- Full Season | Last 30 Days | Last 14 Days | Last 7 Days

*Batting columns:* PA, HR, R, RBI, SB, AVG, OBP, SLG, OPS
*Pitching columns:* IP, W, SV, SO, ERA, WHIP, K/9, BB/9

#### 2. Advanced Stats
Deeper metrics for the same time windows:

*Batting:* wOBA, wRC+ (color-coded: green above 120, red below 80), ISO, BABIP, K%, BB%, WAR
*Pitching:* FIP, xFIP, SIERA, K-BB%, WAR

#### 3. Statcast
Large metric cards displaying:
- Avg Exit Velocity, Max Exit Velocity, Barrel%, Hard Hit%, xBA, xSLG, xwOBA, Sweet Spot%, Sprint Speed, Whiff%, Chase%

Plus a Statcast Trends table comparing these metrics across Full Season, Last 30, and Last 14 periods.

#### 4. Projections
All available projection systems in a table:
- **Steamer, ZiPS, ATC, THE BAT** — External projection systems (if loaded)
- **Blended** — The app's custom weighted projection (highlighted in blue)

#### 5. Comparables
Cards showing the most statistically similar players based on a distance metric. Each card displays key stats and a similarity score — lower distance = more similar.

**Performance Trend Chart:**
A Plotly line chart at the bottom showing wRC+, wOBA, and AVG across rolling time periods (Full Season → Last 30 → Last 14 → Last 7) on dual y-axes. This visualizes whether a player is trending up or down.

**Why it matters for fantasy:** This is your one-stop shop for evaluating any player. The four time periods let you see if a player is getting better or worse. The Statcast tab reveals whether a hot streak is backed by real improvement in contact quality (sustainable) or just lucky BABIP (not sustainable). The Comparables tab helps you discover similar players you might not have considered. And the Projections tab lets you compare what different systems expect from this player rest-of-season.

---

### Matchups

**What it shows:**

Three sections designed to help with daily and weekly lineup decisions:

#### Streaming Pitchers
A ranked table of today's probable pitchers scored by matchup quality (0–100):

| Column | Description |
|--------|-------------|
| Pitcher | Name and team |
| vs | Opposing team |
| Park | Ballpark for the game |
| Score | Streaming score (green 70+, yellow 50–69, red below 50) |
| Proj K | Projected strikeouts for this start (~5.5 IP average) |
| ERA | The pitcher's ERA |
| Notes | Reasoning (e.g., "Strong ERA/FIP, pitcher-friendly park") |

The streaming score combines: pitcher quality (40%), opponent quality (35%), park factor (15%), and recent form (10%).

#### Hitter Stacks
The best team offenses to target today:

| Column | Description |
|--------|-------------|
| Team | The team to stack |
| vs | Opposing pitcher |
| Park | Ballpark |
| Score | Stack quality score |
| Reasoning | Why this stack is good (e.g., "Facing high-ERA pitcher, hitter-friendly park") |

#### Two-Start Pitchers
Pitchers scheduled for two starts this week:

| Column | Description |
|--------|-------------|
| Pitcher | Name and team |
| Start 1 / Start 2 | The two opponents |
| Combined Score | Overall value considering pitcher quality and both matchups |
| Reasoning | Details on each matchup |

**Why it matters for fantasy:** Weekly lineup optimization is one of the biggest edges in fantasy baseball. Streaming pitchers (picking up a pitcher for a single favorable start) can add 2–3 wins and 15+ strikeouts over the course of a season. Hitter stacks exploit the fact that when one batter in a lineup has a big day, his teammates often do too (they bat around). Two-start pitchers get double the opportunity for wins and Ks, making them must-starts if the matchups are favorable.

---

### Compare Players

**What it shows:**

A powerful side-by-side comparison tool inspired by Baseball Savant's percentile rankings and FanGraphs' player rater. Compare up to 5 players across every stat dimension.

**How to use it:**

1. **Search and add players** — Type a player name in the search bar. Click a result to add them to the player dock (top bar). Use position filter pills to narrow results.
2. **Drag to compare** — Drag player chips from the dock into comparison slots below. You can also click an empty slot to focus the search input.
3. **Explore tabs** — Once 2+ players are in slots, the comparison panels activate with 6 tabs.

**Quick Compare presets:** Click "Top 5 1B", "Buy Low Targets", or "Today's Streamers" to auto-populate with relevant players.

#### Tab 1: Overview (Percentile Bars)

Baseball Savant-style horizontal bars showing each player's percentile rank (0–100) for key metrics. Color coding:
- Deep blue (0–10): well below average
- Light blue (31–50): slightly below average
- Light red (51–70): slightly above average
- Deep red (91–100): elite

Use the "Stat Set" dropdown to switch between Statcast metrics, Traditional stats, or All.

#### Tab 2: Stats Table

Standard side-by-side stat table with controls for:
- **Period:** Full Season, Last 30, Last 14, Last 7 days
- **Type:** Standard, Advanced, Statcast

Green highlighting marks the best value in each row; red marks the worst. Use this to quickly identify who leads in each category.

#### Tab 3: Projections

Rest-of-season projection cards showing projected stats, fantasy value (surplus value, positional rank, z-score), and Buy Low / Sell High signals. The xwOBA Delta indicates how much a player is over/under-performing their batted ball quality.

#### Tab 4: Trends

Multi-player line chart showing how a stat has changed across time windows. Use the metric dropdown to switch between AVG, OPS, xwOBA, Barrel%, and Exit Velo. The sparkline row above the chart gives a quick visual overview of multiple metrics.

#### Tab 5: Splits

Platoon and situational splits (vs LHP, vs RHP, Home, Away) displayed side by side. Color-coded: green for strong, red for weak relative to league average. Essential for start/sit decisions against specific pitcher handedness.

#### Tab 6: Radar Chart

Spider/radar chart overlaying player profiles. For hitters, axes are Power, Speed, Contact, Discipline, Batted Ball Quality, and Hit Tool. A larger filled area indicates a more well-rounded player.

**Sharing:** The URL updates with your comparison (?ids=12,45,78). Copy and share it to let others see the same comparison. Your dock persists across browser sessions via localStorage.

**Add from other pages:** Click the "Compare" button on any player card popup to add that player to your comparison dock. A badge on the Compare nav link shows how many players are in your dock.

---

### Player Popup (Quick Look)

**What it shows:**

A modal overlay that appears when you click any player name throughout the app. It provides a quick snapshot without leaving your current page:

- Player name, team, and position
- **Season selector dropdown** — Switch between seasons within the popup
- **Batting stats grid**: PA, HR, R, RBI, SB, AVG, OBP, SLG, OPS, wOBA, wRC+, H
- **Pitching stats** (if applicable): IP, W, L, SV, K, ERA, WHIP, K/9, BB/9, FIP, xFIP, HR
- **Statcast metrics**: Avg EV, Max EV, Barrel%, Hard Hit%, xBA, xSLG, xwOBA, Sweet Spot%

Close the popup by clicking the X button, pressing Escape, or clicking outside the modal.

**Why it matters for fantasy:** Speed matters in fantasy baseball. When you're scanning the waiver wire or evaluating a trade offer, you don't want to navigate away from your current view just to check a player's stats. The popup gives you the essential numbers in seconds.

---

### Intel

**What it shows:**

Daily and weekly AI-generated intelligence reports built from expert fantasy baseball content — blogs (FanGraphs, Pitcher List, RotoWire) and podcast transcripts (CBS Fantasy Baseball Today, FantasyPros, Locked On Fantasy Baseball, In This League). The reports cross-reference expert opinions with your actual league data: roster, projections, standings, and matchup opponent.

Reports are organized by date in the left sidebar. Click any report to view it. The "Refresh Briefing" button generates a fresh daily report on demand.

**Report sections include:**

- **My Roster Intel** — Every player on your roster with a metadata table (Sentiment, Lineup action, Confidence rating, Games This Week, Week-over-Week Trend) and analysis paragraph citing specific expert sources.
- **Injury Watch** — Rostered players with injury concerns, including status, source, and fantasy impact.
- **Matchup Preview** (weekly) — H2H opponent analysis with position-by-position comparison.
- **Waiver Targets** (weekly) — Expert-mentioned free agents cross-referenced with consensus projections.
- **Trade Signals** (weekly) — Buy-low/sell-high opportunities based on expert sentiment vs projection data.
- **Projection Watch** (weekly) — Where expert opinions disagree with Steamer/consensus projections for your players.
- **Around the League** — Big-picture summary of everything discussed across expert sources.
- **Cardinals Corner** (weekly) — Cardinals-relevant news and analysis.
- **Sibling Rivalry** (weekly) — Intel on Ithilien's roster, trade leverage angles, and suggested trade packages.
- **Action Items** — A checklist of specific moves to make, copy-paste ready.

**Schedule:** Daily briefings run automatically at 3 AM (Tue-Fri). Monday reports add a last-week recap with standings and matchup results. Saturday generates the full weekly comprehensive report. All reports also appear in the Obsidian vault if configured.

**Why it matters for fantasy:** Expert analysis from podcasts and blogs often catches things that raw projections miss — spring training velocity changes, role changes, manager quotes, prospect call-up timelines. This page synthesizes all of that and tells you exactly how it affects your team, with linked player names (to FanGraphs) and source citations (to original articles).

---

### Chat Assistant

**What it shows:**

An AI-powered analysis panel accessible via the blue chat bubble in the bottom-right corner. It comes with pre-built suggestion prompts:

- "Who should I pick up this week?"
- "Best streaming pitcher today?"
- "Who are the top buy-low targets?"
- "Compare two players for me"
- "Evaluate a trade for me"

You can also type custom questions. The assistant uses your synced data — your roster, league standings, player stats, and projections — to provide personalized analysis.

**Why it matters for fantasy:** Sometimes you don't want to click through multiple pages. Just ask a natural-language question and get analysis back. It's especially useful for complex questions that span multiple data points, like "Should I trade my Vladdy Jr. for their Corbin Burnes?" where the answer requires comparing position scarcity, surplus value, and roster needs.

---

## Understanding the Stats

### Batting Stats — The Basics

These are the foundational numbers you'll see on nearly every page. If you're new to fantasy baseball, start here.

| Stat | What It Measures | Good | Average | Bad | Fantasy Relevance |
|------|------------------|------|---------|-----|-------------------|
| **PA** (Plate Appearances) | Total trips to the plate | 600+ | 500 | < 400 | More PA = more chances to accumulate counting stats. A player who bats leadoff gets more PA than a player batting 8th. |
| **H** (Hits) | Times reaching base via a hit | 180+ | 150 | < 120 | The building block for batting average. |
| **AVG** (Batting Average) | Hits divided by At-Bats | .300+ | .250 | < .220 | One of the five standard roto categories. Volatile in small samples — a 1-for-20 slump tanks AVG fast. Don't panic early in the season. |
| **OBP** (On-Base Percentage) | How often a hitter reaches base (hits + walks + HBP) | .370+ | .320 | < .290 | More complete than AVG because it credits walks. A .250 hitter with a .370 OBP is still very valuable. Used in OBP leagues. |
| **SLG** (Slugging Percentage) | Total bases divided by At-Bats | .500+ | .420 | < .350 | Measures raw power. A .550 SLG hitter is smashing extra-base hits regularly. |
| **OPS** (On-Base Plus Slugging) | OBP + SLG | .850+ | .730 | < .650 | Quick overall offensive measure. Above .900 is a star. Above 1.000 is elite/MVP-caliber. |
| **HR** (Home Runs) | Home runs hit | 35+ | 20 | < 10 | Standard roto category. The most stable counting stat from year to year — a 30 HR hitter usually keeps hitting 25–35. |
| **R** (Runs Scored) | Times crossing home plate | 100+ | 75 | < 55 | Standard roto category. Heavily dependent on batting order position and the quality of teammates hitting behind you. |
| **RBI** (Runs Batted In) | Runs driven in | 100+ | 70 | < 50 | Standard roto category. Like Runs, depends on opportunity — a great hitter on a bad team gets fewer RBI. |
| **SB** (Stolen Bases) | Successful stolen bases | 30+ | 10 | < 5 | Standard roto category. Stolen bases are rare and getting rarer, making them a premium commodity in fantasy. Even 15 SB has significant trade value. |
| **CS** (Caught Stealing) | Failed steal attempts | — | — | 8+ | Some leagues penalize CS. A player with 20 SB and 12 CS may hurt more than help. |
| **ISO** (Isolated Power) | SLG minus AVG | .220+ | .150 | < .100 | Pure extra-base hit power, stripped of singles. A high-ISO hitter produces HR and doubles. Low ISO means mostly singles. |
| **BABIP** (Batting Avg on Balls In Play) | AVG on balls put in play (excludes HR, K, BB) | — | .300 | — | League average is ~.300. A player hitting .350 AVG with a .400 BABIP is probably lucky and due for regression. Conversely, a .220 AVG with a .230 BABIP will likely bounce back. BABIP is your best friend for spotting luck. |

---

### Batting Stats — Advanced

These metrics go deeper than traditional stats and are better predictors of future performance.

| Stat | What It Measures | Good | Average | Bad | Fantasy Relevance |
|------|------------------|------|---------|-----|-------------------|
| **wOBA** (Weighted On-Base Average) | Each way of reaching base weighted by its actual run value | .370+ | .320 | < .290 | More accurate than OPS because it properly values each outcome. A double isn't worth exactly twice a single — wOBA gets the weights right. This is the stat the app uses most heavily for evaluations. |
| **wRC+** (Weighted Runs Created Plus) | Park- and league-adjusted offensive value, scaled to 100 = average | 130+ | 100 | < 80 | The single best number for "how good is this hitter?" A wRC+ of 150 means the hitter is 50% better than average. The app color-codes this: green above 120, red below 80. Because it's park-adjusted, a 120 wRC+ at Petco Park (pitcher-friendly) is just as good as 120 at Coors Field. |
| **K%** (Strikeout Rate) | Percentage of PA ending in a strikeout | < 15% | 22% | > 30% | Lower is better. High-K hitters are riskier for AVG. But context matters — some elite sluggers (like Aaron Judge historically) strike out a lot but make up for it with power. |
| **BB%** (Walk Rate) | Percentage of PA ending in a walk | 12%+ | 8% | < 5% | Higher is better. Walks indicate plate discipline — the player knows the strike zone. High BB% hitters tend to sustain their OBP even during slumps. |
| **WAR** (Wins Above Replacement) | Total contribution in wins vs. a minor-league replacement | 5+ | 2 | < 1 | Not directly a fantasy stat, but useful context. A 6-WAR player is a real-life star. However, WAR includes defense and baserunning, which often don't matter in fantasy. |

---

### Pitching Stats — The Basics

| Stat | What It Measures | Good | Average | Bad | Fantasy Relevance |
|------|------------------|------|---------|-----|-------------------|
| **IP** (Innings Pitched) | Volume of work | 180+ (SP) | 150 (SP) | < 120 (SP) | More innings = more strikeout opportunities and more influence on your rate stats (ERA, WHIP). Workhorses are underrated in fantasy. |
| **W** (Wins) | Games credited as the winning pitcher | 15+ | 10 | < 6 | Standard roto category, but deeply flawed. A pitcher can dominate for 7 innings and get a no-decision if the offense doesn't score. Wins depend heavily on run support and bullpen quality. Don't overpay for wins. |
| **L** (Losses) | Games credited as the losing pitcher | — | — | — | Informational only in most leagues. |
| **SV** (Saves) | Successfully closing out a game with a lead of 3 runs or fewer | 35+ | 25 | < 10 | Standard roto category. Only closers accumulate saves, making them scarce. A dominant RP without the closer role has zero save value. Always monitor closer committees and role changes. |
| **HLD** (Holds) | Setup men protecting a lead before the closer enters | 25+ | 15 | < 5 | Used in some league formats (Saves + Holds leagues). Makes elite setup men like relievers with 80+ K and a 2.50 ERA fantasy-relevant. |
| **SO** (Strikeouts) | Batters struck out | 220+ (SP) | 170 (SP) | < 120 (SP) | Standard roto category. The most skill-driven pitching stat — strikeout rate is highly repeatable year-over-year. If a pitcher struck out 200 last year, expect 180–220 this year. |
| **ERA** (Earned Run Average) | Earned runs allowed per 9 innings | < 3.00 | 4.00 | > 5.00 | Standard roto category. Lower is better. But ERA is heavily influenced by luck (BABIP, strand rate, defense). A pitcher with a 4.50 ERA but elite stuff may be getting unlucky — check their FIP. |
| **WHIP** (Walks + Hits per Inning) | Baserunners allowed per inning | < 1.10 | 1.25 | > 1.40 | Standard roto category. Lower is better. A WHIP under 1.00 is elite. High WHIP pitchers put runners on base constantly, creating stress and blown-up innings. |
| **K/9** (Strikeouts per 9 Innings) | Strikeout rate | 10.0+ | 8.5 | < 6.5 | A better measure of strikeout dominance than raw K totals because it's rate-based. A reliever with 12.0 K/9 in 60 IP is an elite strikeout weapon. |
| **BB/9** (Walks per 9 Innings) | Walk rate | < 2.5 | 3.2 | > 4.0 | Lower is better. Measures control. Pitchers who walk too many batters eventually pay for it with higher ERA and WHIP. |

---

### Pitching Stats — Advanced

These metrics strip away luck and focus on the things a pitcher actually controls.

| Stat | What It Measures | Good | Average | Bad | Fantasy Relevance |
|------|------------------|------|---------|-----|-------------------|
| **FIP** (Fielding Independent Pitching) | ERA estimated from only K, BB, and HR — the three things a pitcher controls | < 3.00 | 4.00 | > 5.00 | **The most important advanced pitching stat for fantasy.** When FIP is much lower than ERA, the pitcher has been unlucky (bad defense, high BABIP) and their ERA will likely drop. When ERA is much lower than FIP, the pitcher has been lucky and their ERA will likely rise. |
| **xFIP** (Expected FIP) | FIP but with a league-average HR rate applied | < 3.20 | 4.00 | > 5.00 | Even more stable than FIP. Removes HR luck on top of BABIP luck. If a pitcher's HR/FB rate is abnormally high, xFIP will be lower than FIP, suggesting the ERA will eventually come down. |
| **SIERA** (Skill-Interactive ERA) | Most sophisticated ERA estimator — accounts for batted ball types | < 3.00 | 3.80 | > 4.50 | The most predictive ERA estimator. SIERA considers how a pitcher's strikeout rate, walk rate, and ground ball rate interact. Among FIP, xFIP, and SIERA, this is the best single number for predicting future ERA. |
| **K-BB%** (Strikeout Rate minus Walk Rate) | The gap between K% and BB% | 20%+ | 12% | < 8% | The simplest measure of pitching dominance. A pitcher who strikes out 30% of batters and walks 5% (K-BB% = 25%) is elite. This stat has one of the strongest year-to-year correlations of any pitching metric. |
| **WAR** (Wins Above Replacement) | Total pitching contribution in wins | 5+ | 2 | < 1 | Same concept as batting WAR, adapted for pitchers. Useful context but not directly a fantasy stat. |

---

### Statcast Metrics

Statcast is MLB's ball-tracking technology — a system of cameras and radar installed in every stadium that measures the speed, spin, and trajectory of every pitch and batted ball. These metrics tell you about the **quality of contact** rather than the **outcomes**, making them powerful predictors of future performance.

| Metric | What It Measures | Good | Average | Bad | Fantasy Relevance |
|--------|------------------|------|---------|-----|-------------------|
| **Avg Exit Velocity** (EV) | Average speed of the ball off the bat (mph) | 92+ | 88 | < 85 | The best single measure of how hard a hitter hits the ball. Higher EV strongly correlates with more HR and higher SLG. If a player's EV is elite but their AVG is low, they're probably getting unlucky. |
| **Max Exit Velocity** | Hardest-hit ball of the season (mph) | 112+ | 108 | < 104 | Shows absolute ceiling of power. Players who can hit 115+ mph have true elite raw power, even if their HR total doesn't show it yet. |
| **Barrel %** | Percentage of batted balls at the ideal combination of exit velocity (98+ mph) and launch angle (26–30°) | 12%+ | 7% | < 4% | **The best predictor of HR power.** A barreled ball produces a batting average above .500 and a slugging percentage above 1.500. A player with a high Barrel% but low HR total is about to start hitting more homers. |
| **Hard Hit %** | Percentage of batted balls at 95+ mph exit velocity | 45%+ | 38% | < 30% | Broader measure of contact quality than Barrel%. Hard-hit balls are more likely to become hits regardless of launch angle. |
| **xBA** (Expected Batting Average) | What a hitter's AVG "should be" based on exit velocity and launch angle | .280+ | .250 | < .220 | Removes fielding, luck, and park effects. When xBA is much higher than actual AVG, the hitter has been unlucky — their AVG will likely rise. |
| **xSLG** (Expected Slugging) | What a hitter's SLG "should be" based on quality of contact | .500+ | .420 | < .350 | Same concept for slugging. A big xSLG-SLG gap means the power numbers are coming. |
| **xwOBA** (Expected Weighted On-Base Average) | What a player's wOBA "should be" based on batted ball quality | .370+ | .320 | < .290 | **The single most important Statcast metric.** This is the foundation of the app's Buy Low / Sell High signals. When xwOBA exceeds wOBA, the player is underperforming their contact quality and is likely to improve. This is the stat you should check first when evaluating any player. |
| **Sweet Spot %** | Percentage of batted balls in the optimal launch angle range (8–32°) | 38%+ | 33% | < 28% | Shows how consistently a hitter makes productive contact. High Sweet Spot% means fewer popups and weak grounders. |
| **Sprint Speed** (ft/sec) | Top running speed | 28+ | 27 | < 26 | Directly relevant for stolen base potential. Also affects infield hit probability and the ability to take extra bases. A fast player with low SB might just need the green light from their manager. |
| **Whiff %** | How often a hitter swings and misses | < 22% | 25% | > 30% | Lower is better for hitters. High Whiff% means more strikeouts, which hurts AVG and reduces opportunities. However, some elite sluggers have high whiff rates but compensate with extreme power on contact. |
| **Chase %** | How often a hitter swings at pitches outside the strike zone | < 22% | 28% | > 33% | Lower is better. Shows plate discipline. A player with a low chase rate is patient and disciplined — they won't expand the zone chasing sliders in the dirt. This predicts sustainable walk rates. |

---

## Key Concepts

### Buy Low / Sell High Signals

This is the single most actionable feature in the app. Here's how it works:

**The core idea:** Expected stats (xwOBA, xBA, xSLG from Statcast) measure the **quality of a player's batted balls** — how hard and at what angle they hit the ball. Actual stats (wOBA, AVG, SLG) measure **outcomes** — which include luck, fielder positioning, and randomness.

When these two diverge significantly, the actual stats will almost always move toward the expected stats over time. This is called **regression to the mean**, and it's one of the most reliable patterns in baseball.

**Buy Low signal** (xwOBA > wOBA by .030 or more):
The player is hitting the ball well but getting unlucky results. Their batting average, HR, and RBI are artificially depressed. This player will almost certainly improve — their leaguemates probably see a struggling player and would trade them cheaply. Acquire them now before the correction happens.

**Sell High signal** (wOBA > xwOBA by .030 or more):
The opposite — the player's results are better than their contact quality warrants. They're getting lucky with soft hits falling in, bloated BABIP, or fortuitous HR/FB rates. Their production will likely decline. Trade them now while their perceived value is inflated.

**Composite gap score:** On the Player Detail page, the app computes a more detailed composite using three gaps:
- xwOBA vs wOBA (weighted 2x because it's the most predictive)
- xBA vs AVG
- xSLG vs SLG
- FIP vs ERA (for pitchers)

A composite score above +.020 triggers a Buy Low badge; below -.020 triggers Sell High.

**Practical advice:**
- Early in the season (April–May), Buy/Sell signals are **most valuable** because small-sample stats are noisy but Statcast data is already reliable after ~50 PA
- Later in the season, gaps tend to close naturally, so signals become less dramatic
- Always check the Player Detail Statcast tab to understand *why* the gap exists before acting

---

### Projection Blending (Consensus Projections)

The app builds a **consensus projection** by averaging three professional rest-of-season projection systems from FanGraphs:

| System | Description |
|--------|-------------|
| **Steamer** | Multi-year track record with aging curves and regression to the mean. The industry-standard baseline. |
| **ZiPS** | Dan Szymborski's system using weighted multi-year data and aging models. Excels at identifying breakouts. |
| **ATC** | Average Total Cost — a crowd-sourced composite of multiple projection systems. Tends to be the most stable. |

These three systems are blended with **equal weights** (33.3% each) into a single consensus projection. Research consistently shows that averaging multiple independent projection systems outperforms any single system — the errors of one system tend to be offset by the others.

**How consensus projections become fantasy points:**
1. The app fetches Steamer, ZiPS, and ATC rest-of-season projections during stats sync
2. Raw stat projections (HR, R, RBI, K, IP, SV, etc.) are averaged across all three systems
3. The blended stats are converted to fantasy points using the league's scoring rules (SV=7, HLD=4, OUT=1.5, ER=-4, K=-0.5, etc.)
4. This produces a single projected ROS fantasy points number for every player

**Consistency across features:** All features in the app — trades, waivers, the optimizer, and weekly matchup projections — derive from this same consensus projection base. A player's projected value is consistent everywhere in the app, so you never see conflicting recommendations.

The Projections page and Player Detail Projections tab also show each system individually, so you can see where Steamer, ZiPS, and ATC agree or disagree on a player.

**Supplementary analytics:** The app also uses Statcast expected stats (xwOBA, xBA, xSLG) and recent performance trends to generate Buy Low / Sell High signals and analytics-adjusted projections (Adj FP column). These supplement the consensus projections with contact-quality context but don't replace them as the primary valuation base.

---

### Confidence Scores

Every projection includes a confidence score (displayed as a visual bar from empty to full). It reflects how much you should trust the projection, calculated from three factors:

| Factor | Max Contribution | How It Scales |
|--------|-----------------|---------------|
| **Sample Size** | 60% | Ramps from low confidence at 50 PA to full at 400+ PA. More plate appearances = more reliable data to project from. Early-season projections for players with 80 PA will have small confidence bars. |
| **Statcast Availability** | 20% | Having Statcast data adds a flat 20% boost because it provides contact quality information beyond traditional stats. Players without Statcast data (minor leaguers, very low PA) will always have lower confidence. |
| **Season Progress** | 20% | Later in the season = more reliable projections. At the All-Star break (50% of the season), this contributes 10%. By September, it's the full 20%. |

**How to interpret:**
- **Full bar (80–100%):** Strong projection. The player has a large sample with Statcast data and the season is well underway. Trust this projection for decisions.
- **Half bar (40–60%):** Moderate confidence. Useful as a guide but treat with caution. The player may have limited PA or be early in the season.
- **Small bar (< 40%):** Low confidence. The projection is based on limited data. Don't make major roster moves solely based on this projection — wait for more data.

---

### Fantasy Points and Surplus Value

The app's primary valuation method uses **projected fantasy points** based on the Galactic Empire league's specific scoring rules. Every player is valued by how many points they're expected to produce for the rest of the season.

**How projected points are calculated:**

The app uses **consensus projections** — an equal-weight average of Steamer, ZiPS, and ATC rest-of-season projections from FanGraphs (see [Projection Blending](#projection-blending)). These are fetched automatically during stats sync and converted to fantasy points using the league scoring formula:

- **Hitters:** R×1 + 1B×1 + 2B×2 + 3B×3 + HR×4 + RBI×1 + SB×2 + CS×(-1) + BB×1 + HBP×1 + K×(-0.5)
- **Pitchers:** OUT×1.5 + K×0.5 + SV×7 + HLD×4 + RW×4 + QS×2 + H×(-0.75) + ER×(-4) + BB×(-0.75) + HBP×(-0.75)

Note: **RW (Relief Wins)** counts only wins earned by relievers. Starter wins do not score points in this league format.

This produces a single number — projected rest-of-season fantasy points — that directly measures how much value each player is expected to generate. The same consensus projection base is used by the trade analyzer, waiver recommendations, and lineup optimizer, ensuring consistent valuations across the entire app.

When consensus projections are unavailable (e.g., before the first stats sync), the app falls back to an internal projection based on actual counting stats scaled to remaining games.

**Surplus Value** = Projected Points − Replacement-Level Points at that position.

Replacement level is the projected output of the first unrostered player at each position:

| Position | Rostered (10 teams) | Replacement Level |
|----------|--------------------|-------------------|
| C | 10 | The 11th-best catcher |
| 1B, 2B, 3B, SS | 10 each | The 11th-best at each position |
| OF | 30 | 3 OF × 10 teams. The 31st-best outfielder. |
| SP | 20 | 2 dedicated SP × 10 teams |
| RP | 20 | 2 dedicated RP × 10 teams |

**Why this matters for trades:**
- An elite closer projecting 450 ROS points with a replacement-level closer at 150 has a surplus of +300. That's massive — equivalent to 43 saves or 67 extra innings pitched.
- A contact hitter projecting 350 points at SS with replacement at 200 has a surplus of +150.
- The closer has nearly double the trade value despite being "just a reliever" in traditional rankings.

When evaluating trades, the app compares total surplus on each side:
- **Fair** — difference < 20 points
- **Slightly favors** one side — 20 to 75 points
- **Heavily favors** one side — > 75 points

The trade analysis also explains *why* in league-specific terms: how much reliever value is changing hands, how many innings of pitching volume you're trading, and what the point gap translates to in saves or IP.

#### Z-Scores (Legacy)

The app also retains a z-score methodology for roto analysis as a secondary view. Z-scores measure how many standard deviations above or below average a player is across the 5x5 categories (HR, R, RBI, SB, AVG for hitters; W, SV, K, ERA, WHIP for pitchers). However, the default view uses the points-based system described above, since it directly reflects your league's actual scoring.

---

### Waiver Wire Scoring

Every waiver recommendation receives a composite score from 0 to 100, calculated from five weighted components that are optimized for H2H Points scoring:

| Component | Weight | What It Measures | How It's Scored |
|-----------|--------|-----------------|-----------------|
| **Projected Points** | 35% | Projected fantasy points (ROS or weekly) | ROS: uses the same consensus projections (Steamer + ZiPS + ATC average) as the trade analyzer and optimizer. Normalized to 0-100 vs top projection. Weekly: consensus rate stats × games, using per-start projections for SP and per-appearance for RP. |
| **Trend** | 25% | Is the player getting better or worse recently? | Compares last-14-day Statcast xwOBA to full-season xwOBA. If xwOBA improved by .030+, score = 80 (HOT). Includes **BREAKOUT detection**: barrel% +3%, hard-hit% +5%, or xwOBA +.030 (any 2 of 3 = breakout bonus of +15). |
| **Positional Scarcity** | 15% | How hard is it to replace this player's position? | Scarce positions in a 10-team league (C, 1B, 2B, 3B, SS — 10 rostered each) score 70. Mid-depth (SP, RP — 20 each) score 60. Deep (OF — 30) score 40. |
| **Scoring Fit** | 15% | Does this player specifically excel in your scoring format? | **Closers** with saves score 85 (SV=7 is premium). **Setup men** with holds score 75 (HLD=4). **Low-K hitters** (K% < 18%) score 75. **Two-start pitchers** get +20 bonus. **Closer vacancy pickups** get +25 bonus. |
| **Schedule Volume** | 10% | How many games does the team play this week? | 7 games = 90, 6 games = 60, 5 games = 35, fewer = 15. Replaces the previous ownership placeholder. ROS view uses neutral 50. |

#### Weekly-Specific Enhancements

| Feature | Description |
|---------|-------------|
| **Two-Start Detection** | SPs with 2+ confirmed starts show "2-START" badge with opponent details. Gets +20 scoring fit bonus because each IP = 4.5 base points. |
| **Reliever Role & Opportunity** | Role badges (CL/SU/MR/LR) with projected save/hold opportunities per week and estimated points from those opportunities. |
| **Closer Vacancy Detection** | When a closer is on the IL (from MLB injury report), the team's setup man gets "CLOSER OPP" badge and +25 scoring fit bonus. |
| **Injury Filtering** | IL players excluded from weekly views. DTD players flagged with yellow badge and 50% projection reduction. |
| **Breakout Detection** | "BREAKOUT" badge for players meeting 2+ Statcast improvement criteria (barrel%, hard-hit%, xwOBA). |

**The Scoring Fit column** is what makes this waiver page unique to your league. In a standard roto league, a setup man with 20 holds isn't exciting. In your league, that's 80 points from holds alone — and the Fit score flags these players. Similarly, a .270 hitter with a 14% K rate doesn't jump off the page in traditional rankings, but in a format where strikeouts cost half a point each, that player's efficiency is genuinely valuable.

**The badges:**
- **BUY LOW** — xwOBA significantly exceeds actual wOBA (underperforming quality of contact)
- **2-START** — Pitcher has two starts this week (massive weekly value)
- **CLOSER OPP** — Setup man on team with injured closer (save opportunity = 7 pts each)
- **BREAKOUT** — Statcast metrics surging in last 14 days
- **DTD** — Day-to-day injury (projection reduced 50% in weekly views)
- **IL** — Injured list (excluded from weekly views)

**The trend label:**
- **HOT** — Last-14-day xwOBA is .015+ higher than full-season (contact quality improving)
- **COLD** — Last-14-day xwOBA is .015+ lower (declining)
- **--** — Stable (within .015 either direction)

---

### Streaming and Stacking

These are two matchup-based strategies that can provide a significant edge in weekly fantasy formats.

#### Streaming Pitchers
**What it is:** Instead of holding a bench pitcher all week, pick up a pitcher for a single favorable start, then drop them afterward for another streamer. Over a full season, streaming can add 5+ wins and 40+ strikeouts to your totals.

**How the app scores streaming matchups (0–100):**
- **Pitcher quality** (40%): Based on ERA, FIP, and K/9. Lower ERA/FIP and higher K/9 = higher score.
- **Opponent quality** (35%): How weak is the opposing lineup? (Weaker opponents = better streaming matchup.)
- **Park factor** (15%): Is the game in a pitcher-friendly park? Petco Park (factor: 0.93) is great for pitchers. Coors Field (factor: 1.38) is a nightmare.
- **Recent form** (10%): How has the pitcher performed in recent starts?

**Score interpretation:**
- **70+** (green): Strong streaming play. Start with confidence.
- **50–69** (yellow): Decent matchup. Viable if you need the volume.
- **Below 50** (red): Risky. Only stream in desperation.

#### Hitter Stacks
**What it is:** Starting 3–4 hitters from the same team when they face a weak opposing pitcher. The logic: if one hitter in a lineup has a big game (say, a 3-HR day), his teammates in the same lineup probably also had a good day because runs come in bunches. Stacking captures this correlation.

**How the app scores stacks:**
- Opposing pitcher weakness (40%): Higher ERA/FIP/xwOBA-against = better stack.
- xwOBA allowed (35%): How much damage do batters do against this pitcher based on Statcast?
- Park factor for hitting (25%): Hitter-friendly parks (Coors, Yankee Stadium) boost the score.

#### Two-Start Pitchers
**What it is:** Pitchers scheduled for two starts in your scoring period. They get double the opportunity for wins, strikeouts, and quality starts — making them especially valuable. A mediocre pitcher with two starts often outscores an ace with one start in counting categories.

The app identifies all pitchers with two starts in the current week, scores them based on quality (ERA, K/9), and shows both opponents so you can assess the matchup difficulty.

---

## Glossary

Quick-reference for every abbreviation and concept used in the app, listed alphabetically.

| Term | Definition |
|------|-----------|
| **AVG** | Batting average: hits divided by at-bats. League average ~.250. |
| **BABIP** | Batting average on balls in play. League average ~.300. Extreme values suggest luck. |
| **Barrel %** | Percentage of batted balls at optimal exit velocity (98+ mph) and launch angle (26–30°). Best predictor of HR power. |
| **BB%** | Walk rate: percentage of plate appearances ending in a walk. Higher is better. |
| **BB/9** | Walks per 9 innings pitched. Lower is better. |
| **Buy Low** | A player whose expected stats (xwOBA) exceed actual stats (wOBA) by .030+. Likely to improve. |
| **Chase %** | How often a hitter swings at pitches outside the strike zone. Lower is better. |
| **Confidence Score** | How reliable a projection is, based on sample size, Statcast availability, and season progress. |
| **CS** | Caught stealing. Failed steal attempts. |
| **ERA** | Earned run average: earned runs per 9 innings. Lower is better. League average ~4.00. |
| **EV** | Exit velocity: speed of the ball off the bat in mph. |
| **FIP** | Fielding independent pitching: ERA estimator based only on K, BB, and HR. Better predictor of future ERA than ERA itself. |
| **H** | Hits. |
| **Hard Hit %** | Percentage of batted balls at 95+ mph exit velocity. |
| **HLD** | Holds: setup men protecting a lead before the closer. |
| **HR** | Home runs. |
| **IP** | Innings pitched. |
| **ISO** | Isolated power: SLG minus AVG. Measures extra-base hit ability. |
| **K%** | Strikeout rate: percentage of plate appearances ending in a strikeout. Lower is better for hitters. |
| **K/9** | Strikeouts per 9 innings. Higher is better for pitchers. |
| **K-BB%** | Strikeout rate minus walk rate. Higher is better. Simple measure of pitching dominance. |
| **L** | Losses (pitching). |
| **Max EV** | Hardest-hit ball of the season in mph. |
| **OBP** | On-base percentage: how often a hitter reaches base. |
| **OPS** | On-base plus slugging: OBP + SLG. Quick measure of overall offense. |
| **PA** | Plate appearances: total trips to the plate. |
| **Park Factor** | How much a ballpark inflates or suppresses run scoring. 1.00 = neutral. Above 1.00 = hitter-friendly. Below 1.00 = pitcher-friendly. |
| **R** | Runs scored. |
| **RBI** | Runs batted in. |
| **Replacement Level** | The production level of the best freely available player at a given position. |
| **SB** | Stolen bases. |
| **Sell High** | A player whose actual stats (wOBA) exceed expected stats (xwOBA) by .030+. Likely to regress. |
| **SIERA** | Skill-interactive ERA: the most predictive ERA estimator, accounting for batted ball type and pitch interactions. |
| **SLG** | Slugging percentage: total bases divided by at-bats. |
| **SO** | Strikeouts (pitching). |
| **Sprint Speed** | Running speed in feet per second. Above 28 ft/s is fast. |
| **Surplus Value** | A player's projected fantasy points (from consensus projections) minus the replacement-level points at their position. Positive = valuable above replacement. |
| **SV** | Saves. Only closers accumulate them. |
| **Sweet Spot %** | Percentage of batted balls at optimal launch angle (8–32°). |
| **VORP** | Value over replacement player: how much better a player is than the best freely available alternative at their position. |
| **W** | Wins (pitching). |
| **WAR** | Wins above replacement: total player contribution in wins. Includes defense, so more useful for real baseball than fantasy. |
| **Whiff %** | How often a hitter swings and misses. Lower is better for hitters. |
| **WHIP** | Walks + hits per inning pitched. Lower is better. League average ~1.25. |
| **wOBA** | Weighted on-base average: each outcome (single, double, HR, BB) weighted by actual run value. More accurate than OPS. League average ~.320. |
| **wRC+** | Weighted runs created plus: park- and league-adjusted offense. 100 = average. 150 = 50% better than average. |
| **xBA** | Expected batting average: what AVG "should be" based on exit velocity and launch angle. |
| **xFIP** | Expected FIP: FIP with a league-average HR rate. Removes HR luck. |
| **xSLG** | Expected slugging: what SLG "should be" based on quality of contact. |
| **xwOBA** | Expected weighted on-base average: the most important Statcast metric. What a player's wOBA "should be" based on batted ball quality. Foundation of Buy/Sell signals. |
| **Z-Score** | How many standard deviations above or below average a player is in a given category. +2.0 = elite, 0.0 = average, -2.0 = poor. |

---

## Tips for Getting the Most Out of This App

- **Sync stats at least once a week** during the season. Daily is ideal. The app's projections and recommendations are only as good as the underlying data.

- **Pay more attention to xwOBA than AVG in April and May.** Batting average is extremely noisy in small samples (a 1-for-15 slump looks terrible), but Statcast data is reliable after just 50 plate appearances. The Buy Low candidates in April are often the breakout stars of June.

- **Use the Player Detail Statcast tab to verify hot streaks.** A player hitting .350 is exciting, but check their Barrel% and Hard Hit%. If those are also elite, the hot streak is real. If they're average, the player is riding a lucky BABIP and will come back to earth.

- **When evaluating trades, look at surplus value, not raw stats.** A great shortstop is more valuable than a great outfielder with similar stats because the replacement-level shortstop is much worse. Surplus value captures this automatically.

- **Check the Matchups page before setting your weekly lineup.** Streaming pitchers can add 2–3 wins and 15+ strikeouts over a season. Two-start pitchers are especially valuable in weekly leagues.

- **Use Projection Comparison when deciding between two players.** The radar chart makes it instantly obvious which player is more balanced vs. more one-dimensional. Both profiles have value — it depends on what your roster needs.

- **Don't ignore the confidence bar.** A flashy projection with a tiny confidence bar is based on limited data. Weight it accordingly. As the season progresses and confidence bars fill up, projections become much more reliable.

- **The FIP vs ERA scatter plot on Stats Explorer is a cheat code for pitchers.** Find pitchers whose ERA is much higher than their FIP — they are almost certainly going to improve. Target them in trades before their ERA drops and their price goes up.

- **Check the Intel tab every morning.** The daily briefing tells you what experts said about your players overnight — it's the fastest way to spot emerging concerns (like a closer losing velocity) or opportunities (like a breakout confirmed by multiple sources) before your league-mates react.

- **Use the Action Items checklist.** Every Intel report ends with a concrete to-do list of roster moves. Copy it into your notes app and check items off as you execute them.

- **The Chat Assistant knows your roster.** Don't just use it for general questions — ask it specifically about your team. "Should I drop [player X] for [player Y]?" will give you a personalized answer based on your actual roster composition and league context.

---

## League Points Dashboard

The **League Points** page is designed specifically for the Galactic Empire H2H Points league. Every number on this dashboard is displayed in **fantasy points** — you never have to mentally convert stats.

### Scoring System Quick Reference

| Batting | Points | Pitching | Points |
|---------|--------|----------|--------|
| Run (R) | 1 | Per Out (OUT) | 1.5 |
| Single (1B) | 1 | Strikeout (K) | 0.5 |
| Double (2B) | 2 | Save (SV) | **7** |
| Triple (3B) | 3 | Hold (HLD) | **4** |
| Home Run (HR) | **4** | Relief Win (RW) | **4** (reliever only — starter wins do not score) |
| RBI | 1 | Quality Start (QS) | 2 |
| Stolen Base (SB) | 2 | Hit Allowed (H) | -0.75 |
| Caught Stealing (CS) | -1 | Earned Run (ER) | **-4** |
| Walk (BB) | 1 | Walk (BB) | -0.75 |
| Hit By Pitch (HBP) | 1 | Hit By Pitch (HBP) | -0.75 |
| Strikeout (K) | -0.5 | | |

### Key Strategic Insights

1. **Relievers are premium.** A save = 7 pts. An elite closer's clean save inning (1 IP, 2K, SV) = 12.5 points. Always roster closers and strong setup men.

2. **Innings are gold.** Each IP = 4.5 pts from outs. A 7-IP quality start = 31.5 pts from outs alone. Prioritize innings-eating starters with low ERAs.

3. **Earned runs are devastating.** ER = -4 points. A 5-ER blowup loses 20 pts from ER alone. Avoid volatile starters and only stream against weak offenses.

4. **Contact hitters have an edge.** Batter K = -0.5. A 150-K player loses 75 pts from Ks vs an 80-K player losing 40 — a 35-point gap. Low-K hitters with moderate power can outscore TTO sluggers.

5. **Walks are free points.** BB = 1 pt for hitters. High-OBP, low-K hitters are systematically undervalued.

6. **Use the 4 P slots strategically.** They can be SP or RP. Load up on starters when you have aces with good matchups, or fill with relievers when few good starts are available.

### How the Model Uses Scoring Weights

The scoring weights directly drive which matchup adjustments matter most:

| Scoring Feature | Weight | Model Implication |
|----------------|--------|-------------------|
| ER = -4 pts | Heaviest negative | Phase 2 (opponent offense) matters most for pitcher projections. A pitcher facing a 115 wRC+ team has ER projection boosted ~5%, costing ~0.8 extra pts per ER. |
| SV = 7 pts | Highest positive | Closer identification is critical. Phase 1 doesn't adjust SV (pitcher-controlled), but volume estimation (appearance rate) directly drives closer value. |
| OUT = 1.5 pts | High positive volume | Innings are the foundation of pitcher value. SP with 7 IP earn 31.5 pts from outs alone. The IP estimation (probable starts × IP/start) is the most impactful projection input. |
| HR = 4 pts | High positive | Phase 1 (opposing pitcher SIERA) and Phase 3 (park factors) have outsized impact on HR projections. A Coors series can boost HR projection by 30%+. |
| K (batter) = -0.5 | Moderate negative | Phase 1 uses the opposing pitcher's actual K% (not SIERA) because K rate is pitcher-specific. Facing a 30% K pitcher vs 15% K pitcher is a 10% swing in hitter K projection. |
| BB (batter) = +1 | Moderate positive | Phase 1 uses opposing pitcher's BB% for the same reason. Wild pitchers = more free points for hitters. |

### Benchmark Stats: What Typical Weeks Look Like

| Scenario | Typical Weekly Points |
|----------|----------------------|
| Elite closer: 3 save opps, 2 clean innings | ~30-35 pts |
| Ace SP: 2 quality starts (14 IP, 16K, 3ER) | ~35-40 pts |
| Elite hitter: 30 PA, 2 HR, 5 R, 5 RBI, 1 SB | ~25-30 pts |
| Average hitter: 25 PA, 0 HR, 3 R, 3 RBI | ~10-12 pts |
| SP blowup: 4 IP, 7ER, 3BB | ~ -15 pts |
| Full team (17 active): typical week | ~120-180 pts |

### Dashboard Sections

- **Top Hitters by Projected Points** — Hitters ranked by projected ROS fantasy points. The "Pts/PA" column shows efficiency.
- **Top Starters** — Starting pitchers ranked by projected points. "Pts/Start" is the key metric for weekly decisions.
- **Reliever Watch** — Closers and setup men ranked by projected points. Role badges show Closer/Setup/Middle.
- **Contact Kings** — Low-K hitters with the best Pts/PA. The "Pts Lost to Ks" column shows the hidden cost of strikeouts.
- **Points Calculator** — Enter any stat line to calculate fantasy points. Use presets to internalize the scoring system.

---

## Backtesting & Analysis Tools

These command-line tools let you validate the projection model against real historical data. Think of it as a scorecard for the app's predictions: did the projections actually pan out? If you want to understand *why* the app recommends a certain player, these tools show the evidence behind the math.

### Running the Data Pipeline

**What it does:** Downloads up to 10 years of historical MLB data (batting stats, pitching stats, Statcast metrics, park factors, and player IDs) from FanGraphs, Baseball Reference, and the Chadwick Bureau. This data is stored locally so the backtesting tools can evaluate projections against what actually happened.

**How to run it:**

```bash
# Download all seasons (2015-2025) — takes 10-15 minutes on first run
uv run python -m scripts.data_pipeline

# Download a single season (faster, useful for updates)
uv run python -m scripts.data_pipeline --season 2024

# Force re-download even if cached data exists
uv run python -m scripts.data_pipeline --force
```

**What you get:**
- `backtest_data.sqlite` — A local database with all the historical data, stored in the project root
- `data/raw/` — Cached CSV files so you don't have to re-download every time

**When to run it:** Once to set up, then again when you want to include a new completed season. The pipeline caches everything locally, so subsequent runs only download what's missing.

---

### Running the Backtest

**What it does:** Puts the projection model through a rigorous test. For each season from 2019 through 2025, it pretends it's the start of that season, builds projections using only data from prior years (no peeking at the answers!), and then checks how close those projections were to what actually happened. This is called "walk-forward" testing — the gold standard for validating prediction models.

**How to run it:**

```bash
# Run the full backtest (all test seasons)
uv run python -m scripts.backtest_harness

# Test specific seasons only
uv run python -m scripts.backtest_harness --seasons 2021-2024

# Use a custom database path
uv run python -m scripts.backtest_harness --db-path path/to/backtest_data.sqlite
```

**What it shows:**

The backtest compares four projection methods head-to-head:

| Method | What it is |
|--------|-----------|
| **Current Model** | The app's projection engine (the one you actually use) |
| **Marcel** | A well-known baseline method that weights recent seasons (5x last year, 4x two years ago, 3x three years ago) and regresses toward league average — named after the monkey, because "a monkey could do it" |
| **Naive (Last Year)** | Simply assumes a player will repeat last season's stats |
| **League Average** | Predicts every player will be league average (the ultimate sanity check) |

**Quality gate:** The backtest includes an automatic PASS/FAIL check. The current model must beat Marcel by at least 5% on RMSE (prediction error), and no individual stat category can regress more than 3% versus Marcel. If you see PASS, the projections are working. If you see FAIL, something needs investigation.

**What you get:**
- CSV files in `data/results/` with detailed per-player, per-season accuracy data
- A JSON summary with overall scores for each method

---

### Analysis Reports

**What they do:** Five specialized scripts that each test a specific assumption the projection model makes. Each one produces an Excel workbook with live formulas — you can open them in Excel or Google Sheets and see (and modify) the actual math.

**How to run them:**

```bash
# Run from the project root — each creates an Excel file in analysis/
uv run python -m scripts.analysis.analyze_dampening
uv run python -m scripts.analysis.analyze_dynamic_weights
uv run python -m scripts.analysis.analyze_park_factors
uv run python -m scripts.analysis.analyze_platoon_replacement
uv run python -m scripts.analysis.analyze_xwoba_regression
```

**The five analyses:**

| Script | What it tests |
|--------|--------------|
| `analyze_dampening` | How much should we adjust hitter projections based on the quality of opposing pitchers? Tests different dampening levels to find the sweet spot between overreacting and ignoring matchups. |
| `analyze_dynamic_weights` | How should we blend traditional stats (AVG, OBP) with Statcast data (exit velocity, barrel rate) at different points in the season? Early on, prior-year data matters more; later, current-season data takes over. |
| `analyze_park_factors` | How aggressively should park effects be applied? Playing at Coors Field boosts HR projections, but by how much? Tests multiple multiplier strengths. |
| `analyze_platoon_replacement` | Should we adjust for lefty/righty matchups, pitcher quality, or both? Compares three approaches: platoon splits only, pitcher quality only, and a combined multiplicative method. |
| `analyze_xwoba_regression` | Does Statcast's xwOBA (expected weighted on-base average, based on exit velocity and launch angle) predict future performance better than traditional wOBA? Tests pure xwOBA, pure wOBA, and various blends. |

**Where to find the output:** Each script saves an Excel file in the `analysis/` directory. The spreadsheets contain conditional formatting (green = good, red = bad) and cell comments explaining the formulas, so you can explore the results without needing to read code.

---

### Parameter Optimization

**What it does:** Uses mathematical optimization (Nelder-Mead algorithm via scipy) to search for the best possible projection parameters. Instead of guessing at weights and thresholds, it systematically tries thousands of combinations and finds the ones that would have produced the most accurate projections historically.

The parameters it tunes include:
- How much weight to give full-season vs. last-30-days vs. last-14-days stats
- How much weight to give traditional stats vs. Statcast metrics
- How aggressively to adjust for opposing pitcher quality (dampening factors)
- The minimum signal threshold before making an adjustment

**How to run it:**

```bash
# Run in validation mode (safe — tests against historical data only)
uv run python -m scripts.optimize_parameters --mode validation

# Test specific seasons
uv run python -m scripts.optimize_parameters --mode validation --seasons 2024,2025

# Increase iterations for a more thorough search (slower but more precise)
uv run python -m scripts.optimize_parameters --max-iter 1000
```

**Important note:** The optimizer is currently in **validation mode only**, meaning it tests parameter changes against historical data but does not apply them to the live projection engine. Production mode activates on **April 30, 2026**, once enough real 2026 in-season data exists to validate against.

**What you get:** A JSON report in `data/optimization/` showing the best parameters found, how much they improve over the current defaults, and per-stat breakdowns.

---

### Understanding the Results

**Where to learn more:** For a deep dive into the methodology, statistical approach, and design decisions, see `docs/BACKTESTING_METHODOLOGY.md`.

**Key metrics you'll see in the results:**

| Metric | What it means | Good values |
|--------|--------------|-------------|
| **RMSE** (Root Mean Squared Error) | Average prediction error, in the same units as the stat. An RMSE of 0.025 for wOBA means projections are typically off by about 25 points of wOBA. | Lower is better. Compare across methods — if our model's RMSE is lower than Marcel's, we're adding value. |
| **R-squared** (R²) | How much of the variation in actual results the model explains. An R² of 0.60 means the model explains 60% of player-to-player differences. | Higher is better. Above 0.50 is solid for baseball projections; above 0.70 is excellent. |
| **MAE** (Mean Absolute Error) | Similar to RMSE but doesn't penalize big misses as harshly. Useful as a "typical error" measure. | Lower is better. Usually a bit smaller than RMSE. |

**What PASS/FAIL means:**
- **PASS** — The projection model beats the Marcel baseline by at least 5% on overall RMSE, and no individual stat (HR rate, K%, wOBA, ERA, etc.) regresses more than 3% versus Marcel. The model is adding real value beyond what a simple historical average would give you.
- **FAIL** — Either the overall improvement is below 5%, or one or more stats regressed. This doesn't mean the projections are bad — Marcel is already a decent method — but it means the model needs tuning before the added complexity is justified.
