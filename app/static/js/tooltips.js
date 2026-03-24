/**
 * Info Tooltip System
 *
 * Centralized tooltip content and click-based tooltip engine.
 * All stat definitions and page descriptions live here — one file to update.
 */

// ── Content Dictionary ──

const TOOLTIP_DATA = {
  pages: {
    // Dashboard sections
    "dashboard": {
      title: "Dashboard",
      description: "Your home base — league standings, top players, and buy/sell signals at a glance. Check daily during the season to spot trends and stay ahead of your leaguemates."
    },
    "league-standings": {
      title: "League Standings",
      description: "Current W-L-T records and Points For from your Yahoo Fantasy league. Your team is highlighted. Use this to track where you stand and identify rivals to target in trades."
    },
    "my-team": {
      title: "My Team",
      description: "A quick snapshot of your Yahoo Fantasy roster showing your first 12 players with their current position assignments."
    },
    "starting-lineup": {
      title: "Starting Lineup",
      description: "Your active roster players (excluding bench, IL, and NA) with their season-long actual and projected fantasy points. Actual = points earned so far. Projected = estimated rest-of-season total. Use this to spot underperformers who might need benching."
    },
    "weekly-lineup": {
      title: "Weekly Lineup",
      description: "Your roster with projected fantasy points for the current week, powered by 4-phase matchup adjustments (opposing pitcher quality, team offense, park factors, platoon splits). Shows team games, two-start pitcher badges (2S), and injury flags. The optimizer suggests lineup changes to maximize weekly points. Click 'Analyze Lineup' for AI-powered start/sit recommendations. Bench players shown in a collapsible section with their projected points so you can evaluate whether they should start.\n\nNote: This total may differ from the Weekly Matchup page. The lineup widget computes projections live each time you load the dashboard, while the matchup page uses a saved snapshot from the last sync. Additionally, points here are rounded to whole numbers. The matchup page is the more detailed reference for head-to-head comparison."
    },
    "weekly-outlook": {
      title: "Weekly Outlook",
      description: "AI-generated fantasy analyst column covering your H2H matchup, key players to watch, standings context, schedule and weather factors, injury alerts, and personalized sections (Cardinals Corner, Ithilien Watch). Written in the voice of an ESPN/The Athletic columnist. Click to generate — uses your matchup data, projected breakdowns, league standings, and MLB schedule."
    },
    "matchup-analysis": {
      title: "Weekly Matchup Analysis",
      description: "Your current H2H matchup with player-by-player projected vs actual stats. Each category column shows P (projected) and A (actual). Three projection rows: Yahoo Projected (Yahoo's own estimate), My Projected (schedule-aware custom model), and Actual (live from Yahoo sync)."
    },
    "buy-low": {
      title: "Buy Low",
      description: "Players whose expected performance (xwOBA from Statcast) exceeds their actual results. They're hitting the ball well but getting unlucky — their stats will likely improve. Target these players in trades while their perceived value is low."
    },
    "sell-high": {
      title: "Sell High",
      description: "Players whose actual stats exceed their expected performance. They're getting lucky — soft hits falling in, blooped singles, fortunate HR/FB rates. Trade them now while their perceived value is inflated, before regression brings their numbers back down."
    },
    "top-hitters": {
      title: "Top Hitters",
      description: "The best hitters in baseball ranked by OPS (minimum 50 PA). Click any column header to re-sort. Use the search box to filter by name. All player names are clickable for detailed stats."
    },
    "top-pitchers": {
      title: "Top Pitchers",
      description: "The best pitchers ranked by ERA (minimum 20 IP). Click any column header to re-sort. Pay special attention to the FIP column — when FIP is much lower than ERA, the pitcher has been unlucky and their ERA will likely drop."
    },

    // Roster
    "roster": {
      title: "My Roster",
      description: "Your Yahoo Fantasy roster split into Batters and Pitchers, grouped by position slot. Stat columns populate dynamically from available data. Use this to spot underperformers who might need to be benched or dropped."
    },

    // Trade Analyzer
    "trade-analyzer": {
      title: "Trade Analyzer (H2H Points)",
      description: "All trade values use your league's scoring system (SV=7, HLD=4, OUT=1.5, ER=-4, K=-0.5). Each player's value is their projected rest-of-season fantasy points above replacement. The analysis explains why a trade is good or bad in your specific format — highlighting reliever premium, innings value, and K-rate impact."
    },
    "trade-value-rankings": {
      title: "Trade Value Rankings",
      description: "Players ranked by Surplus Value — projected fantasy points above what a replacement-level player at the same position would produce. Positive (green) = worth more than a waiver pickup. Negative (red) = below replacement. Closers and innings-eating starters often rank surprisingly high because SV=7 and IP=4.5 in this format."
    },
    "ai-trade-suggestions": {
      title: "AI Trade Suggestions",
      text: "Scans all opponents' rosters against your team's weak spots using five projection systems (Consensus (Steamer+ZiPS+ATC+Depth Charts+THE BAT X blend), Steamer standalone, and Actual Points). Suggests aggressive and conservative trade packages with specific players, or recommends standing pat if no trade improves your team."
    },
    "ai-trade-analysis": {
      title: "AI Trade Analysis",
      text: "AI-powered narrative analysis of this specific trade using your roster context, three projection systems, Statcast trends, injury status, and league scoring rules. Explains what the numbers mean for your team."
    },

    // Waivers
    "waivers": {
      title: "Waiver Wire (H2H Points)",
      description: "Recommendations optimized for your scoring system. Projected Points (35%) is the primary factor, with bonuses for players who fit this format: closers (SV=7), setup men (HLD=4), low-K hitters (K=-0.5), and innings eaters (IP=4.5). The Fit column flags players with extra value in your specific league that standard rankings miss. Use the dropdown to switch between full-season and weekly projections."
    },
    "intel": {
      title: "Intel — Expert Analysis",
      description: "Daily reports generated by analyzing blog articles (FanGraphs, Pitcher List) and podcast transcripts (CBS Fantasy Baseball Today, FantasyPros) against your league data. Reports include: Daily Briefing (expert mentions of your players), Waiver Intel (expert-hyped free agents), Trade Intel (buy-low/sell-high signals), and Projection Watch (where experts disagree with consensus). Auto-generated at 3 AM or refresh on demand."
    },
    "projection-analysis": {
      title: "Projection Analysis",
      description: "Tracks Yahoo vs app projection accuracy across completed matchup weeks. Shows mean absolute error (MAE), directional accuracy (correctly predicting wins), and which system was closer each week. Use this to calibrate how much trust to place in each projection source as the season progresses."
    },
    "league-standings": {
      title: "League Standings",
      description: "Current league standings with W-L-T records and cumulative Points For/Against. The 'This Week' columns show Yahoo's projected points and actual points scored so far for the current matchup week. Your team is highlighted in blue."
    },
    "league-projection-accuracy": {
      title: "League-Wide Projection Accuracy",
      description: "Yahoo projection accuracy for every team in the league. MAE (Mean Absolute Error) shows how far off Yahoo's projections typically are for each team. Volatility (σ) measures how much a team's weekly scores vary. Most predictable teams are easier to project against; volatile teams create more upset potential."
    },
    "waiver_period": {
      title: "Projection Period",
      description: "Full Season (ROS): ranks players by rest-of-season projected fantasy points. This Week / Next Week: ranks players by projected points for that specific week, factoring in team schedule (number of games), two-start pitchers, reliever opportunities, and matchup quality. Weekly mode excludes injured (IL) players and penalizes day-to-day (DTD) players."
    },
    "waiver_analysis": {
      title: "AI Roster Analysis",
      description: "Sends your current roster, the top waiver targets, injury report, and league scoring to Claude AI for personalized pickup/drop recommendations. The analysis considers your roster's weak spots, two-start pitchers, closer vacancies, Statcast breakout candidates, and injury status. Injury data is sourced from the MLB Official Injury Report."
    },

    // Stats Explorer
    "stats-explorer": {
      title: "Stats Explorer",
      description: "Interactive charts that reveal patterns you can't see in tables. Toggle between Statcast, Batting, and Pitching views. Use the 'Highlight player' search to find and mark a specific player across all charts. Hover over any data point for details. Your roster players appear as gold stars, other rostered players as blue circles, and free agents as green X marks. Click any point to open that player's detail page."
    },
    "ev-vs-barrel": {
      title: "Exit Velocity vs Barrel Rate",
      description: "Each dot is a player, color-coded by xwOBA. Players in the upper-right corner hit the ball hard AND barrel it up frequently — they're the best power hitters in baseball. Look for free agents (green X marks) in the upper-right quadrant for waiver pickups."
    },
    "xwoba-vs-woba": {
      title: "xwOBA vs Actual wOBA (Luck Chart)",
      description: "Players above the diagonal line have xwOBA higher than their actual wOBA — they're underperforming and likely to improve (buy low). Players below the line are overperforming (sell high). The further from the line, the stronger the signal."
    },
    "xwoba-distribution": {
      title: "xwOBA Distribution",
      description: "Shows how expected performance is spread across all players. A player's position on this curve tells you how they compare to the field. The highlighted player line helps you see where a specific player falls."
    },
    "wrc-plus-leaders": {
      title: "wRC+ Leaders",
      description: "The best hitters ranked by Weighted Runs Created Plus. The reference line at 100 marks league average. Every point above 100 means the hitter is that percentage better than average. This is park-adjusted, so a 130 wRC+ at Petco is just as impressive as 130 at Coors."
    },
    "k-vs-bb": {
      title: "K% vs BB% (Plate Discipline)",
      description: "Plate discipline chart. Lower-left is the sweet spot (low strikeouts, high walks). Upper-right means swing-and-miss with poor pitch recognition — a red flag for sustainable production. Players in the lower-left tend to maintain their production over time."
    },
    "woba-distribution": {
      title: "wOBA Distribution",
      description: "Shows the spread of actual offensive performance (wOBA) across all players. Compare a player's position here vs. the xwOBA distribution to spot luck-driven outliers."
    },
    "fip-vs-era": {
      title: "FIP vs ERA",
      description: "Points below the diagonal have ERA higher than FIP — they've been unlucky and their ERA should drop (buy low). Points above the line have ERA lower than FIP — they've been lucky and may regress (sell high). FIP strips away defense and luck to show true pitching skill."
    },
    "k-bb-leaders": {
      title: "K-BB% Leaders",
      description: "Strikeout rate minus walk rate — the simplest measure of pitching dominance. A bigger gap means the pitcher dominates batters (high K) while maintaining control (low BB). This stat has one of the strongest year-to-year correlations in baseball."
    },
    "era-distribution": {
      title: "ERA Distribution",
      description: "Shows the range of ERA across all qualified pitchers. Helps you contextualize whether a pitcher's ERA is truly elite, average, or concerning relative to the league."
    },

    // Projections
    "projections": {
      title: "Projections",
      description: "Rest-of-season projections generated by blending traditional stats (50% weight) with Statcast expected stats (50% weight) across multiple time periods. The confidence bar shows how reliable each projection is based on sample size and data availability. BUY/SELL signals flag players whose expected performance diverges from actual results."
    },
    "buy-low-candidates": {
      title: "Buy Low Candidates",
      description: "Players whose Statcast expected wOBA (xwOBA) is higher than their actual wOBA. They're making quality contact but getting unlucky results. The larger the gap, the more likely they are to improve. These players are undervalued — acquire them in trades before the correction happens."
    },
    "sell-high-candidates": {
      title: "Sell High Candidates",
      description: "Players whose actual wOBA exceeds their Statcast expected wOBA. Their results are better than their contact quality warrants — lucky BABIP, fortunate HR/FB rates, or soft hits finding holes. Trade them while their perceived value is high."
    },
    "projection-comparison": {
      title: "Projection Comparison",
      description: "Compare up to 4 players side by side using blended projections. The radar chart normalizes stats to 0–100 scale for visual comparison. For pitchers, ERA and WHIP are inverted (lower = better = further from center). Use this when deciding between trade targets or waiver pickups."
    },

    // Player Detail
    "standard-stats": {
      title: "Standard Stats",
      description: "Traditional batting or pitching stats across four time windows: Full Season, Last 30 Days, Last 14 Days, and Last 7 Days. Compare periods to see if a player is trending up or down."
    },
    "advanced-stats": {
      title: "Advanced Stats",
      description: "Deeper metrics that better predict future performance than traditional stats. wRC+ is the single best number for hitters. FIP is the best ERA predictor for pitchers. These stats strip away luck and context to show true skill."
    },
    "statcast-tab": {
      title: "Statcast Metrics",
      description: "Ball-tracking data from MLB's Statcast system measuring quality of contact (exit velocity, barrel rate) and expected outcomes (xBA, xSLG, xwOBA). These metrics predict future performance better than traditional stats because they measure how well a player hits the ball, not just outcomes."
    },
    "projections-tab": {
      title: "Projections",
      description: "Rest-of-season projections from multiple systems. Steamer, ZiPS, ATC, and THE BAT are external projection systems. The Blended row (highlighted) is the consensus average of Steamer, ZiPS, and ATC professional projection systems."
    },
    "comparables-tab": {
      title: "Most Similar Players",
      description: "Players with the most statistically similar profiles based on a distance metric across key stats. Lower distance = more similar. Useful for finding comparable players you might not have considered for trades or pickups."
    },
    "performance-trend": {
      title: "Performance Trend",
      description: "Line chart showing wRC+, wOBA, and AVG across rolling time periods (Full Season → Last 30 → Last 14 → Last 7). Upward trends suggest improvement; downward trends signal decline. Cross-reference with the Statcast tab to see if trends are backed by contact quality changes."
    },

    // Matchups
    "matchups": {
      title: "Daily Matchups",
      description: "Matchup-based recommendations for daily and weekly lineup optimization. Streaming pitchers for favorable one-start pickups, hitter stacks to exploit weak opposing pitchers, and two-start pitchers for maximum counting stat accumulation."
    },
    "streaming-pitchers": {
      title: "Streaming Pitchers",
      description: "Today's probable pitchers ranked by matchup quality (0–100). Score combines pitcher quality (40%), opponent weakness (35%), park factor (15%), and recent form (10%). Green scores (70+) are strong plays. Over a full season, streaming can add 5+ wins and 40+ strikeouts."
    },
    "hitter-stacks": {
      title: "Hitter Stacks",
      description: "Best team offenses to target today. Stacking means starting 3–4 hitters from the same team facing a weak pitcher. When one hitter has a big game, his teammates often do too because runs come in bunches. The score factors in opposing pitcher weakness (40%), xwOBA allowed (35%), and park factor (25%)."
    },
    "two-start-pitchers": {
      title: "Two-Start Pitchers",
      description: "Pitchers scheduled for two starts this week. They get double the opportunity for wins and strikeouts, making them especially valuable in weekly formats. A mediocre pitcher with two starts often outscores an ace with one start in counting categories."
    },

    // Player Card Popup
    "player-card": {
      title: "Player Quick Look",
      description: "Quick stats snapshot without leaving your current page. Use the season dropdown to check historical data. Click the player name link at the top to visit the full Player Detail page for deeper analysis."
    },

    // Compare Page
    "compare": {
      title: "Player Comparison Tool",
      description: "Side-by-side player comparison with Baseball Savant-style percentile bars, stat tables, projections, trend charts, splits, and radar profiles. Search for players, drag them into comparison slots, and switch between tabs to analyze from different angles. Share comparisons via URL."
    },
    "compare-overview": {
      title: "Percentile Overview",
      description: "Baseball Savant-style percentile bars showing where each player ranks relative to all qualified players. Blue bars indicate below-average performance, red bars indicate above-average. The deeper the color, the more extreme the percentile. Use the Stat Set dropdown to toggle between Statcast, Traditional, and All metrics."
    },
    "compare-stats": {
      title: "Stat Comparison Table",
      description: "Side-by-side stat table with leader highlighting. Green cells indicate the best value in the comparison group; red indicates the worst. Use Period and Type selectors to drill into recent performance or advanced metrics."
    },
    "compare-projections": {
      title: "Projection Comparison",
      description: "Rest-of-season projections from multiple professional systems. Shows individual projections (Steamer, ZiPS, ATC, The BAT) plus a consensus blend (equal-weight average of available systems). Buy Low / Sell High signals highlight players whose Statcast expected stats diverge from actual performance."
    },
    "compare-trends": {
      title: "Performance Trends",
      description: "Rolling trend lines showing how each player's stats have changed across time windows (Full Season, Last 30, Last 14, Last 7 days). Rising lines indicate improving performance. Use the sparkline row for a quick overview of multiple metrics at once."
    },
    "compare-splits": {
      title: "Splits Comparison",
      description: "Platoon (vs LHP / vs RHP) and home/away splits for each player. Critical for start/sit decisions — a hitter who crushes lefties but struggles against righties should only be started when facing a southpaw."
    },
    "compare-radar": {
      title: "Radar Chart",
      description: "Visual player profile overlay using percentile-based axes. Hitter axes: Power, Speed, Contact, Discipline, Batted Ball Quality, Hit Tool. Larger area = more well-rounded player. Useful for quickly identifying player archetypes and complementary strengths."
    },
    // League Points Dashboard sections
    "league_scoring": {
      title: "League Scoring System",
      description: "Galactic Empire H2H Points league scoring. Every number on this dashboard is in fantasy points. Key: Saves=7 (premium!), Holds=4, each IP=4.5 pts from outs, ER=-4 (devastating), batter K=-0.5 (contact matters), BB=1 (free points)."
    },
    "top_hitters_points": {
      title: "Top Hitters by Points",
      description: "Hitters ranked by projected rest-of-season fantasy points in this scoring system. Points/PA is the key rate stat — it shows efficiency independent of playing time. Surplus value shows points above a replacement-level player at that position."
    },
    "innings_eaters": {
      title: "Innings Eaters",
      description: "Starting pitchers ranked by total projected points. In this scoring, each IP = 4.5 points just from outs (3 outs × 1.5). A starter who averages 6.5 IP = 29.25 points from outs alone. Volume starters with low ERAs are the most valuable arms."
    },
    "reliever_watch": {
      title: "Reliever Watch",
      description: "Relievers ranked by projected points. SV=7 makes elite closers premium — a clean save inning with 2K = 12.5 pts. HLD=4 makes setup men valuable too. The P-slot flexibility (4 slots can be SP or RP) makes this section critical for weekly optimization."
    },
    "contact_kings": {
      title: "Contact Kings",
      description: "Hitters with the best points/PA rate who strike out less than 20% of the time. With K=-0.5, a player who strikes out 150 times loses 75 points vs one who strikes out 80 (35 pt gap). These players are systematically undervalued on the waiver wire."
    },
    "points_calculator": {
      title: "Points Calculator",
      description: "Enter any stat line to see the exact fantasy points. Use the presets to internalize the scoring system. Key benchmarks: elite start = 24.5 pts, closer save = 12.5 pts, bad start can be -17+ pts."
    },
  },

  stats: {
    // ── Batting Basics ──
    "PA": {
      name: "Plate Appearances",
      description: "Total trips to the plate. More PA means more chances to accumulate counting stats like HR, R, and RBI. A player batting leadoff gets more PA than one batting 8th.",
      fantasy: "More PA = more opportunities for R (1pt), HR (4pt), RBI (1pt), BB (1pt). Volume matters.",
      good: "600+", avg: "500", bad: "<400", dir: "higher"
    },
    "H": {
      name: "Hits",
      description: "Times reaching base via a hit. The foundation for batting average.",
      fantasy: "Singles = 1pt, doubles = 2pt, triples = 3pt, HR = 4pt. More hits = more points.",
      good: "180+", avg: "150", bad: "<120", dir: "higher"
    },
    "AVG": {
      name: "Batting Average",
      description: "Hits divided by at-bats. Extremely volatile in small samples — don't panic over a slow April. Check xBA for a truer picture.",
      fantasy: "Higher AVG means more singles (1pt each). Check xBA to see if the AVG is sustainable.",
      good: ".300+", avg: ".250", bad: "<.220", dir: "higher"
    },
    "OBP": {
      name: "On-Base Percentage",
      description: "How often a hitter reaches base (hits + walks + HBP). More complete than AVG because it credits walks.",
      fantasy: "BB = 1pt, HBP = 1pt. High OBP hitters earn free points through walks.",
      good: ".370+", avg: ".320", bad: "<.290", dir: "higher"
    },
    "SLG": {
      name: "Slugging Percentage",
      description: "Total bases divided by at-bats. Measures raw power — extra-base hits are weighted more heavily.",
      fantasy: "Higher SLG means more extra-base hits. 2B=2pt, 3B=3pt, HR=4pt — power drives points.",
      good: ".500+", avg: ".420", bad: "<.350", dir: "higher"
    },
    "OPS": {
      name: "On-Base Plus Slugging",
      description: "OBP + SLG. Quick overall measure of offensive production. Above .900 is a star, above 1.000 is MVP-caliber.",
      fantasy: "Good shorthand for overall fantasy value. .900+ hitters are elite point producers.",
      good: ".850+", avg: ".730", bad: "<.650", dir: "higher"
    },
    "HR": {
      name: "Home Runs",
      description: "The most stable counting stat year-to-year — a 30 HR hitter usually hits 25–35 the next year. Check Barrel% for true power potential.",
      fantasy: "HR = 4pts — the highest-value single event for hitters. Most impactful counting stat.",
      good: "35+", avg: "20", bad: "<10", dir: "higher"
    },
    "R": {
      name: "Runs Scored",
      description: "Heavily dependent on batting order position and teammate quality. A great hitter on a bad team will score fewer runs.",
      fantasy: "R = 1pt. Dependent on lineup position — leadoff hitters on good teams score the most.",
      good: "100+", avg: "75", bad: "<55", dir: "higher"
    },
    "RBI": {
      name: "Runs Batted In",
      description: "Like Runs, depends on opportunity — a great hitter on a bad team gets fewer RBI.",
      fantasy: "RBI = 1pt. Context-dependent — middle-of-order hitters on stacked lineups earn the most.",
      good: "100+", avg: "70", bad: "<50", dir: "higher"
    },
    "SB": {
      name: "Stolen Bases",
      description: "Stolen bases are scarce and getting scarcer, making them a premium commodity. Even 15 SB has significant trade value.",
      fantasy: "SB = 2pts, CS = -1pt. Net positive even at ~60% success. Speed is scarce and valuable.",
      good: "30+", avg: "10", bad: "<5", dir: "higher"
    },
    "CS": {
      name: "Caught Stealing",
      description: "Failed steal attempts.",
      fantasy: "CS = -1pt. Track SB/CS ratio — below 60% success rate costs net points.",
      good: "<3", avg: "5", bad: "8+", dir: "lower"
    },
    "ISO": {
      name: "Isolated Power",
      description: "SLG minus AVG — pure extra-base hit power with singles stripped out. High ISO means lots of doubles and homers.",
      fantasy: "Pure power metric. High ISO = more HR (4pt) and 2B (2pt). Ignores singles entirely.",
      good: ".220+", avg: ".150", bad: "<.100", dir: "higher"
    },
    "BABIP": {
      name: "Batting Avg on Balls in Play",
      description: "AVG on balls put in play (excludes HR, K, BB). League average is ~.300. A player hitting .350 with .400 BABIP is likely getting lucky. A .220 hitter with .230 BABIP will likely bounce back.",
      fantasy: "Luck detector. High BABIP (.360+) often regresses down. Low BABIP (.260-) = buy low opportunity.",
      good: ".330+", avg: ".300", bad: "<.270"
    },

    // ── Batting Advanced ──
    "wOBA": {
      name: "Weighted On-Base Average",
      description: "Each way of reaching base weighted by actual run value — a HR is worth more than a single. More accurate than OPS. This is the stat the app uses most heavily for player evaluation.",
      fantasy: "Best single rate stat for hitter fantasy value. Compare to xwOBA to find buy-low/sell-high.",
      good: ".370+", avg: ".320", bad: "<.290", dir: "higher"
    },
    "wRC+": {
      name: "Weighted Runs Created Plus",
      description: "Park- and league-adjusted offense scaled to 100 = average. 150 means 50% better than average. The single best number for 'how good is this hitter?'",
      fantasy: "Single best rate stat for overall hitter value. 130+ is elite, 80- is replacement level.",
      good: "130+", avg: "100", bad: "<80", dir: "higher"
    },
    "K%": {
      name: "Strikeout Rate",
      description: "Percentage of PA ending in a strikeout. Lower is generally better — high-K hitters are risky for AVG.",
      fantasy: "K = -0.5pts. A 150-K season loses 75 pts from Ks alone. Lower is much better in this league.",
      good: "<15%", avg: "22%", bad: ">30%", dir: "lower"
    },
    "BB%": {
      name: "Walk Rate",
      description: "Percentage of PA ending in a walk. Indicates plate discipline — the hitter knows the strike zone.",
      fantasy: "BB = 1pt. High walk rate = free points every game. Pairs perfectly with low K%.",
      good: "12%+", avg: "8%", bad: "<5%", dir: "higher"
    },
    "WAR": {
      name: "Wins Above Replacement",
      description: "Total contribution in wins vs. a replacement-level player. Includes defense and baserunning.",
      fantasy: "Includes defense (irrelevant for fantasy). Better as a tiebreaker than a primary metric.",
      good: "5+", avg: "2", bad: "<1", dir: "higher"
    },

    // ── Pitching Basics ──
    "IP": {
      name: "Innings Pitched",
      description: "Volume of work. More innings = more K opportunities and more influence on rate stats.",
      fantasy: "Each IP = 4.5pts from outs alone (3 outs × 1.5). Volume starters are gold in this league.",
      good: "180+ (SP)", avg: "150 (SP)", bad: "<120 (SP)", dir: "higher"
    },
    "W": {
      name: "Wins",
      description: "Deeply flawed stat. A pitcher can dominate for 7 innings and get a no-decision. Depends on run support.",
      fantasy: "Starter wins don't score in your league. Only relief wins (RW) = 4pts for relievers.",
      good: "15+", avg: "10", bad: "<6"
    },
    "L": {
      name: "Losses",
      description: "Games credited as the losing pitcher. Mostly informational.",
      good: "—", avg: "—", bad: "—"
    },
    "SV": {
      name: "Saves",
      description: "Only closers accumulate saves, making them scarce. Monitor closer committees and role changes constantly.",
      fantasy: "SV = 7pts — the highest-value single event in your league. Elite closers are premium assets.",
      good: "35+", avg: "25", bad: "<10", dir: "higher"
    },
    "HLD": {
      name: "Holds",
      description: "Setup men protecting a lead before the closer enters.",
      fantasy: "HLD = 4pts. Elite setup men (high K, low WHIP) are valuable — especially for the 4 flex P slots.",
      good: "25+", avg: "15", bad: "<5", dir: "higher"
    },
    "SO": {
      name: "Strikeouts (Pitching)",
      description: "The most skill-driven pitching stat. Highly repeatable year-to-year.",
      fantasy: "Pitcher K = 0.5pts. High-K pitchers rack up points and suppress hits. K/9 is the rate version.",
      good: "220+ (SP)", avg: "170 (SP)", bad: "<120 (SP)", dir: "higher"
    },
    "K": {
      name: "Strikeouts",
      description: "The most skill-driven pitching stat. K rates are highly repeatable year-to-year.",
      fantasy: "Pitcher K = 0.5pts. Also suppresses hits — fewer balls in play = fewer H (-0.75pts each).",
      good: "220+ (SP)", avg: "170 (SP)", bad: "<120 (SP)", dir: "higher"
    },
    "ERA": {
      name: "Earned Run Average",
      description: "Earned runs per 9 innings. Heavily influenced by luck (BABIP, defense, strand rate). When ERA >> FIP, the pitcher has been unlucky.",
      fantasy: "ER = -4pts — the most devastating negative event. Check FIP for true skill level.",
      good: "<3.00", avg: "4.00", bad: ">5.00", dir: "lower"
    },
    "WHIP": {
      name: "Walks + Hits per Inning",
      description: "Baserunners allowed per inning. Below 1.00 is elite. High-WHIP pitchers create blow-up risk.",
      fantasy: "H = -0.75pts, BB = -0.75pts. Low WHIP = fewer baserunners = fewer earned runs.",
      good: "<1.10", avg: "1.25", bad: ">1.40", dir: "lower"
    },
    "K/9": {
      name: "Strikeouts per 9 Innings",
      description: "Rate-based strikeout measure — better than raw K totals for comparing pitchers with different workloads.",
      fantasy: "Pitcher K = 0.5pts. High K/9 racks up points per inning. 10+ K/9 is elite.",
      good: "10.0+", avg: "8.5", bad: "<6.5"
    },
    "BB/9": {
      name: "Walks per 9 Innings",
      description: "Walk rate — measures control. Pitchers who walk too many batters eventually pay with higher ERA and WHIP.",
      fantasy: "BB = -0.75pts. Low BB/9 = efficiency and fewer baserunners leading to ER (-4pts).",
      good: "<2.5", avg: "3.2", bad: ">4.0", dir: "lower"
    },

    // ── Pitching Advanced ──
    "FIP": {
      name: "Fielding Independent Pitching",
      description: "ERA estimated from only K, BB, and HR — things a pitcher controls. When FIP << ERA, the pitcher has been unlucky.",
      fantasy: "Best predictor of future ERA. If FIP << ERA, buy low — the ERA will likely drop.",
      good: "<3.00", avg: "4.00", bad: ">5.00", dir: "lower"
    },
    "xFIP": {
      name: "Expected FIP",
      description: "FIP with league-average HR rate. Even more stable than FIP for predicting future ERA.",
      fantasy: "Most stable pitcher projection metric. Use for rest-of-season projections over ERA or FIP.",
      good: "<3.20", avg: "4.00", bad: ">5.00", dir: "lower"
    },
    "SIERA": {
      name: "Skill-Interactive ERA",
      description: "The most sophisticated ERA estimator — accounts for how K rate, BB rate, and ground ball rate interact.",
      fantasy: "Best ERA estimator available. Great for identifying undervalued streaming pitchers.",
      good: "<3.00", avg: "3.80", bad: ">4.50", dir: "lower"
    },
    "K-BB%": {
      name: "Strikeout Minus Walk Rate",
      description: "The simplest measure of pitching dominance — the gap between K% and BB%. Has one of the strongest year-to-year correlations.",
      fantasy: "Best single rate stat for pitcher quality. K = +0.5pts, BB = -0.75pts — bigger gap = more points.",
      good: "20%+", avg: "12%", bad: "<8%", dir: "higher"
    },

    // ── Statcast ──
    "Avg EV": {
      name: "Average Exit Velocity",
      description: "Average speed off the bat in mph. The best single measure of how hard a hitter hits.",
      fantasy: "Higher EV = harder contact = more extra-base hits and HR (4pts). Core quality metric.",
      good: "92+", avg: "88", bad: "<85", dir: "higher"
    },
    "Avg Exit Velo": {
      name: "Average Exit Velocity",
      description: "Average speed off the bat in mph. The best single measure of how hard a hitter hits.",
      fantasy: "Higher EV = harder contact = more extra-base hits and HR (4pts). Core quality metric.",
      good: "92+", avg: "88", bad: "<85", dir: "higher"
    },
    "Max EV": {
      name: "Max Exit Velocity",
      description: "Hardest-hit ball of the season in mph. Shows absolute ceiling of power.",
      fantasy: "Shows raw power ceiling. High maxEV + low barrel% = unrealized power upside — buy low.",
      good: "112+", avg: "108", bad: "<104", dir: "higher"
    },
    "Max Exit Velo": {
      name: "Max Exit Velocity",
      description: "Hardest-hit ball of the season in mph. Shows absolute ceiling of power.",
      fantasy: "Shows raw power ceiling. High maxEV + low barrel% = unrealized power upside — buy low.",
      good: "112+", avg: "108", bad: "<104", dir: "higher"
    },
    "Barrel %": {
      name: "Barrel Rate",
      description: "% of batted balls at ideal exit velocity (98+ mph) and launch angle (26–30°). A barreled ball averages .500+ AVG and 1.500+ SLG.",
      fantasy: "Best predictor of HR (4pts) and SLG. Barrels become HR ~70% of the time.",
      good: "12%+", avg: "7%", bad: "<4%", dir: "higher"
    },
    "Barrel%": {
      name: "Barrel Rate",
      description: "% of batted balls at ideal exit velocity (98+ mph) and launch angle (26–30°). A barreled ball averages .500+ AVG and 1.500+ SLG.",
      fantasy: "Best predictor of HR (4pts) and SLG. Barrels become HR ~70% of the time.",
      good: "12%+", avg: "7%", bad: "<4%", dir: "higher"
    },
    "Hard Hit %": {
      name: "Hard Hit Rate",
      description: "% of batted balls at 95+ mph exit velocity. Broader contact quality measure than Barrel%.",
      fantasy: "Broader quality metric. High hard hit% sustains batting average and drives extra-base hits.",
      good: "45%+", avg: "38%", bad: "<30%", dir: "higher"
    },
    "Hard Hit%": {
      name: "Hard Hit Rate",
      description: "% of batted balls at 95+ mph exit velocity. Broader contact quality measure than Barrel%.",
      fantasy: "Broader quality metric. High hard hit% sustains batting average and drives extra-base hits.",
      good: "45%+", avg: "38%", bad: "<30%", dir: "higher"
    },
    "HardHit%": {
      name: "Hard Hit Rate",
      description: "% of batted balls at 95+ mph exit velocity. Broader contact quality measure than Barrel%.",
      fantasy: "Broader quality metric. High hard hit% sustains batting average and drives extra-base hits.",
      good: "45%+", avg: "38%", bad: "<30%", dir: "higher"
    },
    "xBA": {
      name: "Expected Batting Average",
      description: "What AVG 'should be' based on exit velocity and launch angle, removing fielding and luck.",
      fantasy: "If xBA >> actual AVG, the player is unlucky — AVG should rise. Buy low opportunity.",
      good: ".280+", avg: ".250", bad: "<.220", dir: "higher"
    },
    "xSLG": {
      name: "Expected Slugging",
      description: "What SLG 'should be' based on quality of contact.",
      fantasy: "Measures true power production independent of luck. A big xSLG-SLG gap = power is coming.",
      good: ".500+", avg: ".420", bad: "<.350", dir: "higher"
    },
    "xwOBA": {
      name: "Expected Weighted On-Base Average",
      description: "The most important Statcast metric. What wOBA 'should be' based on batted ball quality. The foundation of Buy Low / Sell High signals.",
      fantasy: "Best single metric for true offensive ability. Compare to actual wOBA to find buy-low/sell-high.",
      good: ".370+", avg: ".320", bad: "<.290", dir: "higher"
    },
    "Sweet Spot %": {
      name: "Sweet Spot Rate",
      description: "% of batted balls at the optimal launch angle range (8–32°). Shows consistent productive contact.",
      fantasy: "Sweet spot = line drives and fly balls that become hits. Sustains AVG and BABIP long-term.",
      good: "38%+", avg: "33%", bad: "<28%", dir: "higher"
    },
    "Sweet Spot%": {
      name: "Sweet Spot Rate",
      description: "% of batted balls at the optimal launch angle range (8–32°).",
      fantasy: "Sweet spot = line drives and fly balls that become hits. Sustains AVG and BABIP.",
      good: "38%+", avg: "33%", bad: "<28%", dir: "higher"
    },
    "Sprint Speed": {
      name: "Sprint Speed",
      description: "Top running speed in feet per second. Directly relevant for stolen base potential and infield hit probability.",
      fantasy: "Drives SB (2pts), triples (3pts), and infield hits (1pt). Speed is scarce and valuable.",
      good: "28+", avg: "27", bad: "<26", dir: "higher"
    },
    "Whiff %": {
      name: "Whiff Rate",
      description: "How often a hitter swings and misses. Lower is better — high whiff% leads to more strikeouts.",
      fantasy: "High whiff% = high K% = losing 0.5pts per strikeout. Lower is better.",
      good: "<22%", avg: "25%", bad: ">30%", dir: "lower"
    },
    "Whiff%": {
      name: "Whiff Rate",
      description: "How often a hitter swings and misses. Lower is better — high whiff% leads to more strikeouts.",
      fantasy: "High whiff% = high K% = losing 0.5pts per strikeout. Lower is better.",
      good: "<22%", avg: "25%", bad: ">30%", dir: "lower"
    },
    "Chase %": {
      name: "Chase Rate",
      description: "How often a hitter swings at pitches outside the zone. Lower = better plate discipline.",
      fantasy: "Low chase = more walks (BB = 1pt) and fewer Ks (-0.5pts). Discipline is free points.",
      good: "<22%", avg: "28%", bad: ">33%", dir: "lower"
    },
    "Chase%": {
      name: "Chase Rate",
      description: "How often a hitter swings at pitches outside the zone. Lower = better plate discipline.",
      fantasy: "Low chase = more walks (BB = 1pt) and fewer Ks (-0.5pts). Discipline is free points.",
      good: "<22%", avg: "28%", bad: ">33%", dir: "lower"
    },

    // ── App-Specific Columns ──
    "Score": {
      name: "Composite Score",
      description: "Weighted composite score (0–100) combining projection value, recent trend, positional scarcity, ownership, and schedule. Higher = stronger pickup or matchup.",
      good: "70+", avg: "50", bad: "<35"
    },
    "Proj": {
      name: "Projection Score",
      description: "The projection component of the composite score, based on rest-of-season projected output and confidence level. Higher means the player projects for stronger production.",
      good: "—", avg: "—", bad: "—"
    },
    "Trend": {
      name: "Performance Trend",
      description: "Compares last-14-day Statcast xwOBA to full-season xwOBA. HOT = contact quality improving (xwOBA up .015+). COLD = declining. Stable = within .015 either direction.",
      good: "HOT", avg: "—", bad: "COLD"
    },
    "Pos Rank": {
      name: "Positional Rank",
      description: "This player's rank among all players at the same position, based on z-score total. SS #3 means the 3rd-best fantasy shortstop. Lower rank = more valuable.",
      good: "Top 5", avg: "6–12", bad: ">12"
    },
    "Z-Score": {
      name: "Z-Score Total",
      description: "Sum of z-scores across all 5 fantasy categories (HR, R, RBI, SB, AVG for hitters; W, SV, K, ERA, WHIP for pitchers). Higher = more overall fantasy value. Each z-score measures standard deviations above/below average.",
      good: "5.0+", avg: "0", bad: "<-2.0"
    },
    "Surplus": {
      name: "Surplus Value",
      description: "Z-Score Total minus the replacement level at this player's position. Positive means the player is worth more than the best free agent at the same position. The key number for evaluating trades.",
      good: "3.0+", avg: "0.5", bad: "<0"
    },
    "Signal": {
      name: "Buy/Sell Signal",
      description: "BUY (green) = xwOBA exceeds actual wOBA by .030+, the player is underperforming and likely to improve. SELL (red) = actual wOBA exceeds xwOBA by .030+, the player is overperforming and likely to regress.",
      good: "BUY", avg: "—", bad: "SELL"
    },
    "xwOBA Δ": {
      name: "xwOBA Delta",
      description: "The gap between expected wOBA (xwOBA) and actual wOBA. Positive values mean the player is underperforming their contact quality (buy low). Negative values mean overperformance (sell high).",
      good: "+.030+", avg: "±.015", bad: "-.030+"
    },
    "Conf": {
      name: "Confidence Score",
      description: "How reliable this projection is (0–100%). Based on sample size (60%), Statcast data availability (20%), and season progress (20%). Small bars mean limited data — treat the projection cautiously.",
      good: "80%+", avg: "50%", bad: "<30%"
    },
    "Gap": {
      name: "xwOBA Gap",
      description: "The difference between xwOBA and actual wOBA. In the Buy Low panel, positive gaps mean the player deserves better results. In Sell High, negative gaps mean results will likely decline.",
      good: "+.040+", avg: "±.015", bad: "-.040+"
    },
    "Proj K": {
      name: "Projected Strikeouts",
      description: "Estimated strikeouts for this start based on the pitcher's K/9 rate and an average of ~5.5 innings pitched. Higher projected K = more fantasy value from this start.",
      good: "7+", avg: "5", bad: "<4"
    },
    "Notes": {
      name: "Matchup Notes",
      description: "Key factors influencing the streaming or stack score — pitcher quality, park factor, opponent strength. Green notes are positive factors, red notes are concerns.",
      good: "—", avg: "—", bad: "—"
    },

    // ── League Points Metrics ──
    "projected_points": {
      name: "Projected ROS Points",
      dir: "higher",
      description: "Projected rest-of-season fantasy points powered by a consensus blend of five professional projection systems (Steamer, ZiPS, ATC, Depth Charts, and THE BAT X), scored with your league's H2H Points weights (SV=7, HLD=4, OUT=1.5, ER=-4, K=-0.5). Consensus blending averages multiple independent forecasts for greater accuracy than any single system. Falls back to pace-based projection (actual stats scaled to remaining games) when consensus data is unavailable. Once in-season stats accumulate, Statcast adjustments layer on top for buy/sell signal detection.",
      good: "400+", avg: "200", bad: "<100"
    },
    "actual_points": {
      name: "Actual Points",
      description: "Fantasy points earned so far this season using the league's scoring rules. Compare to projected points — if actual is much lower, the player may be underperforming (buy low).",
      good: "—", avg: "—", bad: "—"
    },
    "points_per_pa": {
      name: "Points per Plate Appearance",
      description: "Fantasy points per PA — the key efficiency metric for hitters. Accounts for positive (HR, BB, hits) and negative (K) contributions per trip to the plate.",
      fantasy: "The rate that matters most. High Pts/PA + lots of PA = elite fantasy hitter.",
      good: "1.5+", avg: "1.0", bad: "<0.7", dir: "higher"
    },
    "points_per_ip": {
      name: "Points per Inning Pitched",
      description: "Fantasy points per inning — shows pitching efficiency. Accounts for outs (1.5/out), K (0.5), and penalties (ER=-4, H=-0.75, BB=-0.75).",
      fantasy: "Measures how many points a pitcher earns per inning of work. Higher = more efficient.",
      good: "4.0+", avg: "2.5", bad: "<1.5", dir: "higher"
    },
    "points_per_start": {
      name: "Points per Start",
      description: "Average fantasy points per game started. The single best metric for evaluating starting pitchers in this format.",
      fantasy: "Elite aces average 20+. Streamers should project 8+ to be worth starting.",
      good: "20+", avg: "12", bad: "<8", dir: "higher"
    },
    "points_per_appearance": {
      name: "Points per Appearance",
      description: "Average fantasy points per relief appearance.",
      fantasy: "Closers with saves avg 8+ (clean save = 12.5pts). Setup men with holds avg 5-7.",
      good: "8+", avg: "4", bad: "<2", dir: "higher"
    },
    "surplus_value": {
      name: "Surplus Value (Points)",
      description: "Projected points above replacement level at the player's position. The key metric for trade evaluation.",
      fantasy: "Positive = worth rostering. Negative = replaceable by a free agent. Drives all trade logic.",
      good: "100+", avg: "25", bad: "<0", dir: "higher"
    },
    "trade-app-proj": {
      name: "App Projected",
      description: "Our custom ROS projection blending actual stats (traditional + Statcast expected metrics). Weights recent performance and expected stat regression based on quality of contact.",
      good: ">200", avg: "100–200", bad: "<100"
    },
    "trade-steamer": {
      name: "Steamer ROS",
      description: "FanGraphs Steamer rest-of-season projection system — an industry-standard baseline using multi-year track record weighted toward recent performance. Converted to league-specific fantasy points.",
      good: ">200", avg: "100–200", bad: "<100"
    },
    "trade-actual": {
      name: "Actual Points",
      description: "Fantasy points actually scored this season using league scoring rules. Compare to projections to identify over/underperformers.",
      good: ">200", avg: "100–200", bad: "<100"
    },
    "k_points_lost": {
      name: "Points Lost to Strikeouts",
      description: "Total points lost from batter strikeouts (K × -0.5). A 150K hitter loses 75 points from Ks alone vs an 80K hitter losing 40 — a 35 point gap. This column highlights the hidden cost of high strikeout rates in this scoring format.",
      good: "<30", avg: "50", bad: ">70"
    },
    "PF": {
      name: "Points For",
      description: "Total fantasy points scored in your league. Higher is better — even a team with a losing record but high PF is unlucky and likely to improve.",
      good: "—", avg: "—", bad: "—"
    },
    "Status": {
      name: "Waiver Status",
      description: "BUY LOW badge appears when a player's Statcast expected stats significantly exceed their actual results — they're hitting the ball well but getting unlucky. These are the highest-upside waiver pickups.",
      good: "BUY LOW", avg: "—", bad: "—"
    },
    "Reasoning": {
      name: "Recommendation Reasoning",
      description: "Brief explanation of why this player is recommended — which scoring components are strongest (trending up, scarce position, buy-low signal, high projection confidence).",
      good: "—", avg: "—", bad: "—"
    },

    // ── Advanced Analytics (Projections Page) ──
    "HardHit%": {
      name: "Hard Hit Rate",
      description: "Percentage of batted balls at 95+ mph exit velocity. Early-season signal for contact quality — high hard-hit% with low AVG suggests imminent improvement.",
      good: "45%+", avg: "38%", bad: "<30%"
    },
    "SB%": {
      name: "Stolen Base Success Rate",
      description: "Percentage of steal attempts that succeed. At SB=2/CS=-1 scoring, break-even is 33%. Players above 75% with speed are net positive to steal aggressively.",
      good: "80%+", avg: "72%", bad: "<66%"
    },
    "xERA": {
      name: "Expected ERA",
      description: "ERA a pitcher 'should have' based on Statcast contact quality allowed. The best buy/sell signal for pitchers — when xERA is much lower than actual ERA, the pitcher has been unlucky.",
      good: "<3.50", avg: "4.00", bad: ">4.50"
    },
    "K% Pitcher": {
      name: "Strikeout Rate (Pitchers)",
      description: "Percentage of batters faced who strike out. Each K earns +0.5 pts AND prevents a hit. High-K pitchers double-dip on value in this scoring system.",
      good: "28%+", avg: "22%", bad: "<18%"
    },
    "BB% Pitcher": {
      name: "Walk Rate (Pitchers)",
      description: "Percentage of batters walked. Each BB costs -0.75 pts and often leads to ER (-4 pts). Low BB% is critical for pitcher value in H2H Points.",
      good: "<6%", avg: "8%", bad: ">10%"
    },
    "GB%": {
      name: "Ground Ball Rate",
      description: "Percentage of batted balls hit on the ground. Ground balls rarely become HR (reducing ER at -4 pts) and generate more double plays. High GB% = safer pitcher floor.",
      good: "50%+", avg: "44%", bad: "<38%"
    },
    "HR/FB%": {
      name: "HR per Fly Ball Rate",
      description: "Percentage of fly balls that become home runs. League average is ~10-12%. Pitchers below 8% are getting lucky (expect regression). Above 15% are unlucky (expect improvement).",
      good: "<10%", avg: "11%", bad: ">15%"
    },
    "gmLI": {
      name: "Game Leverage Index",
      description: "Average leverage of situations when this reliever enters. 1.0 = average. Above 1.5 = high-leverage reliever trusted in close games. Key for identifying closers-in-waiting.",
      good: "1.5+", avg: "1.0", bad: "<0.7"
    },
    "IP/G": {
      name: "Innings per Game",
      description: "Average innings pitched per appearance. Multi-inning relievers (1.1+ IP/G) earn more volume-based points (1.5 pts per out). Higher IP/G = more total points per appearance.",
      good: "1.2+", avg: "1.0", bad: "<0.8"
    },
    "Adj FP": {
      name: "Adjusted Fantasy Points (Hitters)",
      description: "Projected ROS fantasy points adjusted using xwOBA vs wOBA divergence. Green arrow = underperforming contact quality (buy low). Red arrow = overperforming (sell high). Neutral dash = performance matches expectations.",
      good: "▲ up", avg: "—", bad: "▼ down"
    },
    "matchup-yahoo-proj": {
      name: "Yahoo Projected",
      description: "Yahoo Fantasy's own weekly team projection. Based on Yahoo's internal models and the week's schedule. Frozen when the matchup first loads each week.",
      good: "—", avg: "—", bad: "—"
    },
    "matchup-my-proj": {
      name: "My Projected (Matchup-Adjusted)",
      description: "Four-layer matchup-adjusted projections: (1) Opposing pitcher — hitter stats adjusted by SIERA + pitcher K%/BB%, dampened 50%. (2) Opposing lineup — pitcher H/ER adjusted by team wRC+, dampened 35%. (3) Park factors — base rates neutralized for home park, then venue-adjusted. (4) Platoon splits — when opposing starter handedness is known, uses regressed vs-LHP/RHP splits (per Tango's The Book: 2200 PA regression for RHH, 1000 for LHH). All metrics chosen to avoid double-counting with park factors (SIERA and wRC+ are park-adjusted). Frozen at start of each week.",
      good: "—", avg: "—", bad: "—"
    },
    "Adj FP Pitcher": {
      name: "Adjusted Fantasy Points (Pitchers)",
      description: "Projected ROS fantasy points adjusted using xERA/SIERA vs actual ERA divergence. Green arrow = better than results show. Red arrow = regression risk. For relievers, also flags save opportunity upside when gmLI > 1.5.",
      good: "▲ up", avg: "—", bad: "▼ down"
    },
  }
};


// ── Tooltip Engine ──

let tooltipEl = null;
let currentTooltipKey = null;

function _createTooltip() {
  if (tooltipEl) return;
  tooltipEl = document.createElement("div");
  tooltipEl.id = "info-tooltip";
  tooltipEl.className = "fixed z-[60] max-w-xs bg-gray-800 border border-gray-600 rounded-lg shadow-xl p-3 text-sm";
  tooltipEl.style.display = "none";
  tooltipEl.innerHTML = `
    <div id="info-tooltip-title" class="font-semibold text-white text-sm"></div>
    <div id="info-tooltip-desc" class="text-gray-300 text-xs mt-1 leading-relaxed"></div>
    <div id="info-tooltip-fantasy" class="text-gray-400 text-xs mt-1 italic" style="display:none;"></div>
    <div id="info-tooltip-benchmarks" class="mt-2 flex gap-3 text-xs" style="display:none;">
      <span class="text-green-400" id="info-tooltip-good"></span>
      <span class="text-gray-500" id="info-tooltip-avg"></span>
      <span class="text-red-400" id="info-tooltip-bad"></span>
    </div>
    <div id="info-tooltip-lookfor" class="text-blue-400 text-xs font-medium mt-1" style="display:none;"></div>
  `;
  document.body.appendChild(tooltipEl);
}

function showInfoTooltip(event, key, type) {
  event.stopPropagation();
  _createTooltip();

  // Toggle off if clicking the same icon
  if (currentTooltipKey === type + ":" + key && tooltipEl.style.display !== "none") {
    _hideTooltip();
    return;
  }

  const source = type === "page" ? TOOLTIP_DATA.pages : TOOLTIP_DATA.stats;
  const data = source[key];
  if (!data) return;

  // Populate content
  const title = data.title || data.name || key;
  document.getElementById("info-tooltip-title").textContent = title;
  document.getElementById("info-tooltip-desc").textContent = data.description || "";

  // Fantasy relevance
  const fantasyEl = document.getElementById("info-tooltip-fantasy");
  if (data.fantasy) {
    fantasyEl.textContent = data.fantasy;
    fantasyEl.style.display = "block";
  } else {
    fantasyEl.style.display = "none";
  }

  // Benchmarks
  const benchmarks = document.getElementById("info-tooltip-benchmarks");
  if (data.good && data.good !== "—") {
    document.getElementById("info-tooltip-good").textContent = "Good: " + data.good;
    document.getElementById("info-tooltip-avg").textContent = "Avg: " + data.avg;
    document.getElementById("info-tooltip-bad").textContent = "Bad: " + data.bad;
    benchmarks.style.display = "flex";
  } else {
    benchmarks.style.display = "none";
  }

  // Look for / direction hint
  const lookforEl = document.getElementById("info-tooltip-lookfor");
  if (data.dir) {
    lookforEl.textContent = data.dir === "higher"
      ? "↑ Higher is better"
      : "↓ Lower is better";
    lookforEl.style.display = "block";
  } else {
    lookforEl.style.display = "none";
  }

  // Position near clicked icon
  tooltipEl.style.display = "block";
  const rect = event.currentTarget.getBoundingClientRect();
  const ttRect = tooltipEl.getBoundingClientRect();
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  let top = rect.bottom + 6;
  let left = rect.left - (ttRect.width / 2) + (rect.width / 2);

  // Flip up if near bottom
  if (top + ttRect.height > vh - 10) {
    top = rect.top - ttRect.height - 6;
  }
  // Clamp horizontal
  if (left < 8) left = 8;
  if (left + ttRect.width > vw - 8) left = vw - ttRect.width - 8;

  tooltipEl.style.top = top + "px";
  tooltipEl.style.left = left + "px";

  currentTooltipKey = type + ":" + key;
}

function _hideTooltip() {
  if (tooltipEl) {
    tooltipEl.style.display = "none";
  }
  currentTooltipKey = null;
}

// Close on click outside
document.addEventListener("click", function (e) {
  if (tooltipEl && !tooltipEl.contains(e.target) && !e.target.closest(".info-icon")) {
    _hideTooltip();
  }
});

// Close on Escape (before modal handler gets it)
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape" && tooltipEl && tooltipEl.style.display !== "none") {
    e.stopPropagation();
    _hideTooltip();
  }
}, true); // capture phase so it fires before modal's Escape handler
