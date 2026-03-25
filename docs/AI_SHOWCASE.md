# Lankford Legends — AI-Powered Features

How artificial intelligence turns raw data into a personal fantasy baseball analyst that knows your team, your league, and what the experts are saying.

---

## Overnight Intelligence Pipeline

Every morning at 3 AM, the app automatically:

1. **Pulls the latest fantasy baseball articles** from FanGraphs, Pitcher List, and RotoWire
2. **Downloads new podcast episodes** from CBS Fantasy Baseball Today, FantasyPros, Locked On Fantasy Baseball, and In This League
3. **Transcribes the podcasts** using local speech-to-text
4. **Feeds everything to AI** along with your league data — your roster, your opponent's roster, standings, free agents, and last week's results
5. **Generates a personalized daily briefing** with expert-backed analysis specific to your team

By the time you wake up, there's a fresh intelligence report waiting — not generic fantasy advice, but analysis tailored to your exact situation.

---

## Daily Intelligence Reports

The flagship feature. AI reads through all the expert content and cross-references it with your league data to produce a multi-section briefing:

- **Roster Intel** — Every player on your team gets a sentiment rating (Bullish, Bearish, or Neutral) with a recommended action (Start, Sit, Sell, Drop) and a confidence level. Trend arrows show how sentiment shifted from the previous report.
- **Matchup Preview** — A narrative breakdown of your head-to-head opponent this week: where you have the edge, where you're vulnerable, and which players to watch.
- **Waiver Targets** — Free agents the experts are talking about, filtered and ranked for fit with your team's specific weak spots.
- **Trade Signals** — Sell-high candidates on your roster and buy-low targets on other teams, backed by expert reasoning and projection analysis.
- **Injury Watch** — Context beyond the official injury report: what the experts are saying about timelines, workload concerns, and fantasy impact.
- **Cardinals Corner** — Because the owner is a Cardinals fan, every report includes a dedicated section on STL players across the league.
- **Action Items** — A concrete checklist of every recommendation, ordered by urgency.

Full weekly reports on Saturdays expand to 11 sections including a last-week recap and sibling rivalry analysis (the owner's brother is in the league).

---

## AI Chat Assistant

A conversational assistant available on every page that can:

- **Look up any player's stats** — batting, pitching, Statcast metrics, splits, by any time period
- **Compare players side-by-side** — up to 5 at once with percentile rankings
- **Evaluate trades** — uses your league's exact scoring system to calculate surplus value
- **Find waiver pickups** — identifies free agents that fit your roster's needs
- **Check today's matchups** — streaming pitcher picks, hitter stacks, weather
- **Answer any fantasy question** — "Should I start Witt or Betts this week?" with reasoning tied to your scoring format

The assistant knows your league's custom scoring rules (saves are worth 7 points, holds are 4, strikeouts cost half a point for hitters) and factors them into every recommendation.

---

## Smart Lineup Optimizer

The weekly lineup tool combines three layers of analysis:

1. **Mathematical optimization** — an integer linear programming solver finds the optimal lineup configuration across all position slots, factoring in multi-position eligibility
2. **Four-phase matchup adjustments** — each player's projection is adjusted for opposing pitcher quality, team offense, park factors, and platoon splits
3. **AI start/sit recommendations** — informed by the morning's expert intel, the AI explains why specific moves make sense in plain English

The result: specific swap suggestions with projected point gains, plus narrative reasoning that references what the experts are saying.

---

## Weekly Preview Column

Click one button and get a full analyst-style column covering your matchup for the week — written like you'd read on ESPN or The Athletic:

- Head-to-head storyline with edges and vulnerabilities
- Projection analysis comparing multiple systems
- Key players to watch on both sides
- Schedule advantages, park factors, and weather
- Injury concerns and their fantasy impact
- League standings context and playoff positioning

The preview incorporates insights from the daily intel pipeline, so it's not just numbers — it weaves in what FanGraphs writers, podcast hosts, and analysts are saying about the players in your matchup.

---

## Waiver Wire AI

The waiver page scores every available player using a composite of:

- Rest-of-season projections from multiple systems (Steamer, ZiPS, ATC)
- Your league's specific scoring weights
- Schedule factors (games this week, two-start pitchers)
- Statcast quality metrics (expected stats vs actual — who's due for a breakout?)
- Injury-driven opportunities (closer vacancies, lineup openings)

Then AI analyzes your roster's weak spots and recommends specific add/drop moves with reasoning tied to your team's needs.

---

## Player Intelligence

Every player name in the app is clickable, opening a detailed profile with:

- Full batting or pitching stats across multiple seasons
- Statcast quality metrics (exit velocity, barrel rate, expected stats)
- Links to their [FanGraphs](https://www.fangraphs.com/) player page for deep-dive analytics
- Buy/sell signals based on expected vs actual performance (xwOBA vs wOBA)
- Multi-system projection comparison

---

## Yahoo Fantasy Integration

The app connects directly to your Yahoo Fantasy league and understands:

- Your exact roster and position assignments
- Your league's custom H2H Points scoring system
- All 10 teams' rosters, standings, and matchup schedules
- Waiver wire availability and roster moves

Every AI feature uses this real league data — recommendations aren't generic, they're specific to your team, your opponent, and your scoring format.

---

## How It All Connects

The intelligence pipeline creates a feedback loop:

```
Expert Content (articles + podcasts)
         ↓
   AI Daily Briefing (personalized to your league)
         ↓
   Feeds into → Lineup Analysis
   Feeds into → Weekly Preview
         ↓
   You make better decisions
```

The daily briefing isn't just a standalone report — its insights flow into the lineup optimizer and weekly preview, so every AI feature in the app benefits from the latest expert analysis.

---

*Built with Python, FastAPI, and a whole lot of baseball nerdery.*
