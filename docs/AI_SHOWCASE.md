# Lankford Legends — AI-Powered Features

I built this app because I wanted something better than refreshing Yahoo Fantasy and hoping I made the right start/sit call. What started as a weekend project turned into a full AI-powered fantasy baseball command center that knows my team, my league, and what the experts are saying — before I even wake up.

---

## Overnight Intelligence Pipeline

Every morning at 3 AM, the app automatically:

1. **Pulls the latest fantasy baseball articles** from FanGraphs, Pitcher List, and RotoWire
2. **Downloads new podcast episodes** from CBS Fantasy Baseball Today, FantasyPros, Locked On Fantasy Baseball, and In This League
3. **Transcribes the podcasts** using local speech-to-text
4. **Feeds everything to AI** along with my league data — my roster, my opponent's roster, standings, free agents, and last week's results
5. **Generates a personalized daily briefing** with expert-backed analysis specific to my team

By the time I check my phone in the morning, there's a fresh intelligence report waiting — not generic fantasy advice, but analysis tailored to my exact situation in a 10-team H2H Points keeper league.

---

## Daily Intelligence Reports

The flagship feature. AI reads through all the expert content from the previous day and cross-references it with my league data to produce a multi-section briefing:

- **Roster Intel** — Every player on my team gets a sentiment rating (Bullish, Bearish, or Neutral) with a recommended action (Start, Sit, Sell, Drop) and a confidence level. Trend arrows show how sentiment shifted from the previous report.
- **Matchup Preview** — A narrative breakdown of my head-to-head opponent this week: where I have the edge, where I'm vulnerable, and which players to watch.
- **Waiver Targets** — Free agents the experts are talking about, filtered and ranked for fit with my team's specific weak spots.
- **Trade Signals** — Sell-high candidates on my roster and buy-low targets on other teams, backed by expert reasoning and projection analysis.
- **Injury Watch** — Context beyond the official injury report: what the experts are saying about timelines, workload concerns, and fantasy impact.
- **Cardinals Corner** — I'm a Cardinals fan, so every report includes a dedicated section on STL players across the league.
- **Sibling Rivalry** — My brother's in the league too. The report tracks his team's strengths and weaknesses so I always know where I stand.
- **Action Items** — A concrete checklist of every recommendation, ordered by urgency.

Full weekly reports on Saturdays expand to 11 sections including a recap of last week's matchup and how my players performed.

---

## AI Chat Assistant

There's a conversational assistant available on every page that I can ask anything:

- **Look up any player's stats** — batting, pitching, Statcast metrics, splits, by any time period
- **Compare players side-by-side** — up to 5 at once with percentile rankings
- **Evaluate trades** — it uses my league's exact scoring system to calculate surplus value
- **Find waiver pickups** — identifies free agents that fit my roster's needs
- **Check today's matchups** — streaming pitcher picks, hitter stacks, weather
- **Answer any fantasy question** — "Should I start Witt or Betts this week?" with reasoning tied to my scoring format

The assistant knows my league's custom scoring rules (saves are worth 7 points, holds are 4, strikeouts cost half a point for hitters) and factors them into every recommendation. It's not a generic chatbot — it's connected to my actual league data.

---

## Smart Lineup Optimizer

The weekly lineup tool combines three layers of analysis:

1. **Mathematical optimization** — an integer linear programming solver finds the optimal lineup configuration across all position slots, factoring in multi-position eligibility
2. **Four-phase matchup adjustments** — each player's projection is adjusted for opposing pitcher quality, team offense, park factors, and platoon splits
3. **AI start/sit recommendations** — informed by that morning's expert intel, the AI explains why specific moves make sense in plain English

I get specific swap suggestions with projected point gains, plus narrative reasoning that references what the experts are saying. It's like having a fantasy analyst on staff.

---

## Weekly Preview Column

One button press generates a full analyst-style column covering my matchup for the week — written like something you'd read on ESPN or The Athletic:

- Head-to-head storyline with edges and vulnerabilities
- Projection analysis comparing multiple systems
- Key players to watch on both sides
- Schedule advantages, park factors, and weather
- Injury concerns and their fantasy impact
- League standings context and playoff positioning

The preview pulls in insights from my daily intel pipeline, so it's not just numbers — it weaves in what FanGraphs writers, podcast hosts, and analysts are actually saying about the players in my matchup.

---

## Waiver Wire AI

The waiver page scores every available player using a composite of:

- Rest-of-season projections from multiple systems (Steamer, ZiPS, ATC)
- My league's specific scoring weights
- Schedule factors (games this week, two-start pitchers)
- Statcast quality metrics (expected stats vs actual — who's due for a breakout?)
- Injury-driven opportunities (closer vacancies, lineup openings)

Then AI analyzes my roster's weak spots and recommends specific add/drop moves with reasoning tied to my team's needs. It knows that in my league, a closer producing 35 saves generates 245 points from saves alone — so it prioritizes accordingly.

---

## Player Intelligence

Every player name in the app is clickable, opening a detailed profile with:

- Full batting or pitching stats across multiple seasons
- Statcast quality metrics (exit velocity, barrel rate, expected stats)
- Direct links to their [FanGraphs](https://www.fangraphs.com/) player page for the full deep dive
- Buy/sell signals based on expected vs actual performance — the nerdy way of finding who's getting lucky and who's about to break out
- Multi-system projection comparison (Steamer, ZiPS, ATC blended)

---

## Yahoo Fantasy Integration

The app connects directly to my Yahoo Fantasy league and understands:

- My exact roster and position assignments
- My league's custom H2H Points scoring system (every category weighted differently)
- All 10 teams' rosters, standings, and matchup schedules
- Waiver wire availability and roster moves

Every AI feature uses this real league data — nothing is generic. When the app tells me to start a player, it's because it knows my scoring system, my opponent's roster, and what the matchups look like this week.

---

## How It All Connects

The intelligence pipeline creates a feedback loop:

```
Expert Content (articles + podcasts)
         ↓
   AI Daily Briefing (personalized to my league)
         ↓
   Feeds into → Lineup Analysis
   Feeds into → Weekly Preview
         ↓
   I make better decisions (hopefully)
```

The daily briefing isn't just a standalone report — its insights flow into the lineup optimizer and weekly preview, so every AI feature in the app benefits from the latest expert analysis.

---

This app was built almost entirely through vibe coding with [Claude Code](https://claude.ai/claude-code) in Visual Studio Code by [Brian Renshaw](https://github.com/brianrenshaw) — plus a lot of research into baseball APIs (Yahoo Fantasy, FanGraphs, Statcast, Baseball Reference, MLB Stats API), projection systems, and a whole lot of baseball nerdery.
