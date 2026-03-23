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
  - [Player Popup (Quick Look)](#player-popup-quick-look)
  - [Chat Assistant](#chat-assistant)
- [Understanding the Stats](#understanding-the-stats)
  - [Batting Stats — The Basics](#batting-stats--the-basics)
  - [Batting Stats — Advanced](#batting-stats--advanced)
  - [Pitching Stats — The Basics](#pitching-stats--the-basics)
  - [Pitching Stats — Advanced](#pitching-stats--advanced)
  - [Statcast Metrics](#statcast-metrics)
- [Key Concepts](#key-concepts)
  - [Buy Low / Sell High Signals](#buy-low--sell-high-signals)
  - [Projection Blending](#projection-blending)
  - [Confidence Scores](#confidence-scores)
  - [Z-Scores and Trade Values](#z-scores-and-trade-values)
  - [VORP and Surplus Value](#vorp-and-surplus-value)
  - [Waiver Wire Scoring](#waiver-wire-scoring)
  - [Streaming and Stacking](#streaming-and-stacking)
- [Glossary](#glossary)
- [Tips for Getting the Most Out of This App](#tips-for-getting-the-most-out-of-this-app)

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

- **Sidebar** (left side): Links to all major pages — Dashboard, Roster, Trades, Waivers, Stats Explorer, Projections, and Matchups.
- **Player Search** (top of sidebar): Type any player name to search across the entire database. Results appear as a dropdown — click a name to open their full Player Detail page.
- **Chat Assistant** (bottom-right corner): A blue chat bubble that opens an AI-powered analysis panel. Ask questions about your roster, get trade advice, or request player comparisons.

---

## App Pages

### Dashboard

**What it shows:**

The Dashboard is your home base — a snapshot of your league and the broader baseball landscape.

| Section | Description |
|---------|-------------|
| **League Standings** | Your league's current standings table: rank, team name, W-L-T record, and Points For. Your team is highlighted. |
| **My Team Summary** | The first 12 players on your Yahoo roster with position badges showing where each player is slotted. |
| **Buy Low / Sell High Signals** | Cards highlighting players whose expected performance (xwOBA) significantly differs from their actual results (wOBA). These are trade opportunity alerts. |
| **Category Leaders** | A 4-column grid showing the top players in HR, SB, AVG, and K — the marquee fantasy categories. |
| **Top Hitters** | A sortable, filterable table of the best hitters. Columns: PA, HR, R, RBI, SB, AVG, OBP, SLG, OPS, wOBA, wRC+. Click any column header to sort. |
| **Top Pitchers** | Same format for pitchers. Columns: IP, W, L, SV, K, ERA, WHIP, K/9, BB/9, FIP. |
| **Season Selector** | Dropdown to switch between any season you've synced data for. |

**Interactive features:** Click any column header in the hitter/pitcher tables to sort ascending or descending (arrows indicate direction). Use the search/filter box above each table to quickly find a player. All player names are clickable.

**Why it matters for fantasy:** The Dashboard lets you quickly see where you stand in your league, who the hottest players are right now, and which players are flagged as buy-low or sell-high opportunities. Checking this page regularly keeps you ahead of your leaguemates.

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

Two sections:

1. **Evaluate a Trade** — A form where you enter player IDs for Side A and Side B (comma-separated). Click "Analyze Trade" and the app returns:
   - Total surplus value for each side
   - The value difference between the two sides
   - A fairness rating: **Fair** (difference < 0.5), **Slightly Favors** one side (0.5–2.0), or **Heavily Favors** one side (> 2.0)

2. **Trade Value Rankings** — A table of all players ranked by surplus value, showing:
   - **Pos Rank** — Their rank among players at the same position (e.g., SS #3 means the 3rd-best shortstop)
   - **Z-Score Total** — Sum of z-scores across all fantasy categories (higher = more overall value)
   - **Surplus Value** — How much better this player is than the best freely available player at the same position. Green numbers are positive (valuable); red numbers are negative (below replacement level)

**Why it matters for fantasy:** Trades are won or lost based on understanding true player value. Raw stats can be deceiving — a player with 20 HR might seem great, but if they play outfield (where 20 HR is common), they provide less positional value than a shortstop with 15 HR. The z-score and surplus value system accounts for this, giving you an objective framework to evaluate any trade. See [Z-Scores and Trade Values](#z-scores-and-trade-values) and [VORP and Surplus Value](#vorp-and-surplus-value) for the full methodology.

---

### Waivers

**What it shows:**

A ranked table of waiver wire recommendations — free agents scored from 0 to 100 based on a composite of five factors. Columns include:

| Column | Description |
|--------|-------------|
| **Player** | Name, team, and position |
| **Score** | Composite waiver score (0–100). Higher = stronger pickup. |
| **Proj Score** | How well the player is projected to perform rest-of-season |
| **Trend** | **HOT** (recent Statcast metrics improving), **COLD** (declining), or **--** (stable) |
| **Status** | A **BUY LOW** badge appears when the player's expected stats significantly exceed their actual results |
| **Reasoning** | A brief sentence explaining why this player is recommended |

**Why it matters for fantasy:** The waiver wire is where leagues are won. This page surfaces the best available pickups by looking beyond surface-level stats. A player hitting .220 might rank highly because their Statcast metrics (exit velocity, barrel rate) suggest they're about to break out. The composite scoring ensures you're not just chasing hot streaks — it balances projection quality, recent trends, positional scarcity, and more. See [Waiver Wire Scoring](#waiver-wire-scoring) for the full breakdown.

---

### Stats Explorer

**What it shows:**

An interactive charting dashboard with three tabbed views, each featuring Plotly charts you can hover over, zoom into, and click on:

#### Statcast Tab
- **Exit Velocity vs Barrel Rate** scatter plot — Each dot is a player, color-coded by xwOBA. Players in the upper-right corner hit the ball hard AND frequently barrel it up — these are the best hitters in baseball.
- **xwOBA vs xBA** scatter ("the luck chart") — Compares expected batting average to expected weighted on-base average. Useful for identifying well-rounded hitters vs. one-dimensional ones.
- **xwOBA Distribution** histogram — Shows the spread of expected performance across all players. A player's position on this curve tells you how they compare to the field.

#### Batting Tab
- **wRC+ Leaders** bar chart — Horizontal bars ranking the best hitters by wRC+ (Weighted Runs Created Plus). A reference line at 100 marks league average.
- **K% vs BB%** scatter ("plate discipline chart") — Lower-left is the best spot (low strikeouts, high walks). Upper-right means a player swings and misses a lot while rarely walking — a red flag.
- **wOBA Distribution** histogram — Shows the spread of actual offensive performance.

#### Pitching Tab
- **FIP vs ERA** scatter — Points below the diagonal line have an ERA higher than their FIP, suggesting they've been unlucky and may improve. Points above the line may regress.
- **K-BB% Leaders** bar chart — The gap between strikeout rate and walk rate. Bigger gap = more dominant pitcher.
- **ERA Distribution** histogram — Visualizes the range of ERA across all qualified pitchers.

**Interactive features:** Season selector dropdown, minimum PA filter (default 50), hover tooltips showing player name and exact values, and tab switching. Chart data points for players on your roster appear as gold stars; other rostered players are blue circles; free agents are green X marks. Click any data point to navigate to that player's detail page.

**Why it matters for fantasy:** Charts reveal patterns that tables can't. The FIP vs ERA scatter instantly shows you which pitchers are due for regression. The K% vs BB% plot highlights hitters with elite plate discipline (a strong predictor of sustained success). The Statcast charts bypass traditional stats entirely, showing you which players are making the best contact regardless of their batting average.

---

### Projections

**What it shows:**

Rest-of-season projections for all qualified players, generated by the app's custom [blended projection engine](#projection-blending).

- **Hitter/Pitcher Toggle** — Switch between hitter and pitcher projection views.
- **Position Filter Pills** — For hitters: All, C, 1B, 2B, 3B, SS, OF, DH. For pitchers: All, SP, RP.
- **Season Selector** — View projections based on any synced season's data.

**Hitter Projection Table:**

| Column | Description |
|--------|-------------|
| HR, R, RBI, SB | Projected rest-of-season counting stats |
| AVG, OPS | Projected rate stats |
| Signal | **BUY** (green) or **SELL** (red) badge when xwOBA gap exceeds ±.030 |
| xwOBA Delta | The gap between expected and actual performance |
| Confidence | Visual bar showing how reliable the projection is (see [Confidence Scores](#confidence-scores)) |

**Pitcher Projection Table:**

| Column | Description |
|--------|-------------|
| W, SV, K | Projected rest-of-season counting stats |
| ERA, WHIP | Projected rate stats |
| Signal | BUY/SELL badge |
| Confidence | Reliability indicator |

Below the main table, two side-by-side panels show:
- **Buy Low Candidates** — Players whose xwOBA exceeds their actual wOBA (they're underperforming their contact quality and likely to improve)
- **Sell High Candidates** — Players whose actual wOBA exceeds their xwOBA (they're overperforming and likely to regress)

Each panel shows the player's actual wOBA, xwOBA, and the gap between them.

**Why it matters for fantasy:** Projections are the foundation of every good fantasy decision. Should you start Player A or Player B? Who will produce more HR rest-of-season? This page answers those questions using a blend of traditional stats, recent performance, and Statcast expected stats — not just one data source. The Buy Low / Sell High panels are especially powerful early in the season when small samples create misleading batting averages but Statcast data already tells the real story.

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

### Projection Blending

The app doesn't rely on a single data source. Instead, it blends five inputs with carefully chosen weights:

| Source | Weight | Why This Weight |
|--------|--------|----------------|
| Full Season Traditional Stats | 25% | Largest sample of actual performance. Captures overall skill level. |
| Last 30 Days Traditional Stats | 15% | Detects recent changes — lineup moves, return from injury, approach adjustments. |
| Last 14 Days Traditional Stats | 10% | Most recent form, but small sample size warrants lower weight. |
| Full Season Statcast (xBA, xSLG, xwOBA) | 30% | **Highest weight** because batted-ball quality is the best predictor of future performance. Strips away luck. |
| Last 30 Days Statcast | 20% | Recent trends in contact quality. Catches mechanical changes before they show up in traditional stats. |

**How counting stats are projected (HR, R, RBI, SB, K):**
1. Convert each source's counting stats to per-PA (or per-IP) rates
2. Blend the rates using the weights above
3. Estimate remaining plate appearances for the season (based on pace)
4. Projected total = stats already accumulated + (blended rate × remaining PA)

**How rate stats are projected (AVG, ERA, WHIP):**
1. Directly blend the rate values from each source
2. For batting average, Statcast xBA substitutes for traditional AVG in the Statcast-weighted components
3. For pitchers, ERA projections weight FIP (25%) and xFIP (25%) more heavily than actual ERA (15%) because FIP-based metrics are better predictors of future ERA

**Multi-system blending:** If external projection systems are loaded (Steamer, ZiPS, ATC, THE BAT), the app can also blend these with configurable weights (default: Steamer 30%, ZiPS 25%, ATC 25%, THE BAT 20%). These appear as separate rows on the Player Detail Projections tab.

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

### Z-Scores and Trade Values

**What is a z-score?** In plain terms, a z-score tells you how many standard deviations above or below average a player is in a specific category. If a player has a z-score of +2.0 in HR, it means they hit significantly more home runs than the average player. A z-score of -1.0 in SB means they steal fewer bases than most.

- **+2.0 or higher:** Elite (top ~2.5% of players)
- **+1.0:** Good (top ~16%)
- **0.0:** Exactly average
- **-1.0:** Below average (bottom ~16%)
- **-2.0 or lower:** Poor (bottom ~2.5%)

**The five hitting categories:** HR, R, RBI, SB, AVG (the standard 5x5 roto categories)
**The five pitching categories:** W, SV, K, ERA, WHIP

For ERA and WHIP, the z-score is **inverted** — a lower ERA is better, so a pitcher with a 2.50 ERA gets a positive z-score.

**Z-Score Total** is the sum of z-scores across all five categories. It represents a player's total fantasy value across all categories. A z-score total of +8.0 means the player is elite across the board. A total near 0.0 means the player is roughly average in all categories combined.

---

### VORP and Surplus Value

**VORP (Value Over Replacement Player):** Not all positions are created equal. There are far more productive outfielders than productive catchers. VORP measures how much better a player is than the best freely available player at the same position — the "replacement player."

**How the app defines replacement level:**

In a standard 12-team league, the app assumes these many roster spots per position:

| Position | Roster Spots (12 teams) | Implication |
|----------|------------------------|-------------|
| C | 12 | Only 12 catchers are "owned." The 13th-best catcher is the replacement level. |
| 1B | 12 | Same concept. |
| 2B | 12 | |
| 3B | 12 | |
| SS | 12 | |
| OF | 60 | 5 OF slots × 12 teams. The 61st-best outfielder is replacement level. |
| SP | 84 | ~7 SP × 12 teams. Deep position — replacement-level SP is still decent. |
| RP | 36 | ~3 RP × 12 teams. |

**Surplus Value** = Z-Score Total − Replacement-Level Z-Score Total at that position.

Example: If the 13th-best shortstop has a z-score total of +1.5, then a shortstop with a z-score total of +5.0 has a surplus value of +3.5. That +3.5 represents how much better this player is than what you could get for free on waivers.

**Why this matters for trades:**
- A 1B with 30 HR and a z-score total of +4.0 might have a surplus value of only +1.0 (because first basemen are plentiful and the replacement is decent)
- A SS with 20 HR and a z-score total of +3.0 might have a surplus value of +2.5 (because shortstops are scarce and the replacement is weak)
- The shortstop is actually more valuable in a trade despite having lower raw stats

When evaluating trades, add up the surplus value on each side. The side with the higher total is getting more fantasy value. The app rates trades as:
- **Fair** — difference < 0.5
- **Slightly favors** one side — difference 0.5 to 2.0
- **Heavily favors** one side — difference > 2.0

---

### Waiver Wire Scoring

Every waiver recommendation receives a composite score from 0 to 100, calculated from five weighted components:

| Component | Weight | What It Measures | How It's Scored |
|-----------|--------|-----------------|-----------------|
| **Projection** | 30% | Rest-of-season projected value from the blending engine | Confidence score × 50. A player with a high-confidence strong projection scores highest. |
| **Trend** | 30% | Is the player getting better or worse recently? | Compares last-14-day Statcast xwOBA to full-season xwOBA. If xwOBA improved by .030+, score = 80 (HOT). If it declined by .030+, score = 20 (COLD). Stable players score 50. |
| **Positional Scarcity** | 20% | How hard is it to replace this player's position? | Scarce positions (C, 1B, 2B, 3B, SS — only 12 rostered each) score 70. Mid-depth positions (SP, RP) score 50. Deep positions (OF — 60 rostered) score 30. |
| **Ownership** | 10% | How widely owned is the player? | Currently uses a neutral placeholder (50). Lower-owned players would score higher since they represent untapped upside. |
| **Schedule** | 10% | Are upcoming matchups favorable? | Currently uses a neutral placeholder (50). Favorable upcoming opponents would boost this score. |

**The "BUY LOW" badge** appears when the player's xwOBA significantly exceeds their actual wOBA — the same buy-low signal used throughout the app. A BUY LOW waiver wire player is someone who's hitting the ball well but getting unlucky, sitting on the wire because their surface-level stats look bad. These are the highest-upside pickups.

**The trend label:**
- **HOT** — Last-14-day xwOBA is .015+ higher than full-season (the player's contact quality is improving)
- **COLD** — Last-14-day xwOBA is .015+ lower than full-season (declining)
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
| **Surplus Value** | A player's z-score total minus the replacement-level z-score at their position. Positive = valuable above replacement. |
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

- **The Chat Assistant knows your roster.** Don't just use it for general questions — ask it specifically about your team. "Should I drop [player X] for [player Y]?" will give you a personalized answer based on your actual roster composition and league context.
