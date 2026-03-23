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

    // Waivers
    "waivers": {
      title: "Waiver Wire (H2H Points)",
      description: "Recommendations optimized for your scoring system. Projected Points (35%) is the primary factor, with bonuses for players who fit this format: closers (SV=7), setup men (HLD=4), low-K hitters (K=-0.5), and innings eaters (IP=4.5). The Fit column flags players with extra value in your specific league that standard rankings miss."
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
      description: "Rest-of-season projections from multiple systems. Steamer, ZiPS, ATC, and THE BAT are external projection systems. The Blended row (highlighted) is the app's custom weighted projection combining traditional stats with Statcast data."
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
      description: "Rest-of-season projections from blended projection systems (Steamer, ZiPS, ATC, The BAT). Shows Buy Low / Sell High signals based on the gap between expected (Statcast) and actual performance. The xwOBA Delta is the key indicator."
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
      good: "600+", avg: "500", bad: "<400"
    },
    "H": {
      name: "Hits",
      description: "Times reaching base via a hit. The foundation for batting average.",
      good: "180+", avg: "150", bad: "<120"
    },
    "AVG": {
      name: "Batting Average",
      description: "Hits divided by at-bats. Standard fantasy category. Extremely volatile in small samples — don't panic over a slow April. Check xBA for a truer picture.",
      good: ".300+", avg: ".250", bad: "<.220"
    },
    "OBP": {
      name: "On-Base Percentage",
      description: "How often a hitter reaches base (hits + walks + HBP). More complete than AVG because it credits walks. A .250 hitter with .370 OBP is still very valuable in OBP leagues.",
      good: ".370+", avg: ".320", bad: "<.290"
    },
    "SLG": {
      name: "Slugging Percentage",
      description: "Total bases divided by at-bats. Measures raw power — extra-base hits are weighted more heavily. Directly tied to HR and doubles production.",
      good: ".500+", avg: ".420", bad: "<.350"
    },
    "OPS": {
      name: "On-Base Plus Slugging",
      description: "OBP + SLG. Quick overall measure of offensive production. Above .900 is a star, above 1.000 is MVP-caliber. Useful for quick comparisons but wOBA is more accurate.",
      good: ".850+", avg: ".730", bad: "<.650"
    },
    "HR": {
      name: "Home Runs",
      description: "Standard fantasy category. The most stable counting stat year-to-year — a 30 HR hitter usually hits 25–35 the next year. Check Barrel% for true power potential.",
      good: "35+", avg: "20", bad: "<10"
    },
    "R": {
      name: "Runs Scored",
      description: "Standard fantasy category. Heavily dependent on batting order position and teammate quality. A great hitter batting 6th on a bad team will score fewer runs than a good hitter batting 1st on a stacked lineup.",
      good: "100+", avg: "75", bad: "<55"
    },
    "RBI": {
      name: "Runs Batted In",
      description: "Standard fantasy category. Like Runs, depends on opportunity — a great hitter on a bad team gets fewer RBI. Don't overpay for RBI when they come from lineup context rather than individual skill.",
      good: "100+", avg: "70", bad: "<50"
    },
    "SB": {
      name: "Stolen Bases",
      description: "Standard fantasy category. Stolen bases are scarce and getting scarcer, making them a premium commodity. Even 15 SB has significant trade value because so few players reach that mark.",
      good: "30+", avg: "10", bad: "<5"
    },
    "CS": {
      name: "Caught Stealing",
      description: "Failed steal attempts. Some leagues penalize CS. A player with 20 SB but 12 CS may hurt more than help in those formats.",
      good: "<3", avg: "5", bad: "8+"
    },
    "ISO": {
      name: "Isolated Power",
      description: "SLG minus AVG — pure extra-base hit power with singles stripped out. High ISO means lots of doubles and homers. Low ISO means mostly singles.",
      good: ".220+", avg: ".150", bad: "<.100"
    },
    "BABIP": {
      name: "Batting Avg on Balls in Play",
      description: "AVG on balls put in play (excludes HR, K, BB). League average is ~.300. A player hitting .350 with a .400 BABIP is likely getting lucky. A .220 hitter with .230 BABIP will likely bounce back. Your best tool for spotting luck.",
      good: "—", avg: ".300", bad: "—"
    },

    // ── Batting Advanced ──
    "wOBA": {
      name: "Weighted On-Base Average",
      description: "Each way of reaching base weighted by actual run value — a HR is worth more than a single. More accurate than OPS. This is the stat the app uses most heavily for player evaluation.",
      good: ".370+", avg: ".320", bad: "<.290"
    },
    "wRC+": {
      name: "Weighted Runs Created Plus",
      description: "Park- and league-adjusted offense scaled to 100 = average. 150 means 50% better than average. The single best number for 'how good is this hitter?' Park-adjusted, so a 120 at Petco equals 120 at Coors.",
      good: "130+", avg: "100", bad: "<80"
    },
    "K%": {
      name: "Strikeout Rate",
      description: "Percentage of PA ending in a strikeout. Lower is generally better — high-K hitters are risky for AVG. But some elite sluggers strike out a lot and compensate with power.",
      good: "<15%", avg: "22%", bad: ">30%"
    },
    "BB%": {
      name: "Walk Rate",
      description: "Percentage of PA ending in a walk. Indicates plate discipline — the hitter knows the strike zone. High BB% hitters sustain their OBP even during slumps.",
      good: "12%+", avg: "8%", bad: "<5%"
    },
    "WAR": {
      name: "Wins Above Replacement",
      description: "Total contribution in wins vs. a replacement-level player. Includes defense and baserunning which often don't matter for fantasy, but useful for contextualizing overall real-life value.",
      good: "5+", avg: "2", bad: "<1"
    },

    // ── Pitching Basics ──
    "IP": {
      name: "Innings Pitched",
      description: "Volume of work. More innings = more K opportunities and more influence on rate stats (ERA, WHIP). Workhorses who pitch 180+ IP are underrated in fantasy.",
      good: "180+ (SP)", avg: "150 (SP)", bad: "<120 (SP)"
    },
    "W": {
      name: "Wins",
      description: "Standard fantasy category but deeply flawed. A pitcher can dominate for 7 innings and get a no-decision. Wins depend on run support and bullpen — don't overpay for them.",
      good: "15+", avg: "10", bad: "<6"
    },
    "L": {
      name: "Losses",
      description: "Games credited as the losing pitcher. Mostly informational — not a standard fantasy category in most formats.",
      good: "—", avg: "—", bad: "—"
    },
    "SV": {
      name: "Saves",
      description: "Standard fantasy category. Only closers accumulate saves, making them scarce. A dominant reliever without the closer role has zero save value. Monitor closer committees and role changes constantly.",
      good: "35+", avg: "25", bad: "<10"
    },
    "HLD": {
      name: "Holds",
      description: "Setup men protecting a lead before the closer enters. Used in Saves+Holds league formats. Makes elite setup relievers with high K rates fantasy-relevant.",
      good: "25+", avg: "15", bad: "<5"
    },
    "SO": {
      name: "Strikeouts (Pitching)",
      description: "The most skill-driven pitching stat. Strikeout rates are highly repeatable year-to-year — if a pitcher struck out 200 last year, expect 180–220 this year.",
      good: "220+ (SP)", avg: "170 (SP)", bad: "<120 (SP)"
    },
    "K": {
      name: "Strikeouts",
      description: "The most skill-driven pitching stat. K rates are highly repeatable year-to-year. Check K/9 for the rate-based version when comparing starters vs. relievers.",
      good: "220+ (SP)", avg: "170 (SP)", bad: "<120 (SP)"
    },
    "ERA": {
      name: "Earned Run Average",
      description: "Earned runs per 9 innings. Standard fantasy category, but heavily influenced by luck (BABIP, defense, strand rate). When ERA is much higher than FIP, the pitcher has been unlucky and will likely improve.",
      good: "<3.00", avg: "4.00", bad: ">5.00"
    },
    "WHIP": {
      name: "Walks + Hits per Inning",
      description: "Baserunners allowed per inning. Standard fantasy category. Below 1.00 is elite. High-WHIP pitchers constantly put runners on base, creating blow-up risk.",
      good: "<1.10", avg: "1.25", bad: ">1.40"
    },
    "K/9": {
      name: "Strikeouts per 9 Innings",
      description: "Rate-based strikeout measure — better than raw K totals for comparing pitchers with different workloads. A reliever with 12.0 K/9 in 60 IP is an elite K weapon.",
      good: "10.0+", avg: "8.5", bad: "<6.5"
    },
    "BB/9": {
      name: "Walks per 9 Innings",
      description: "Walk rate — measures control. Pitchers who walk too many batters eventually pay with higher ERA and WHIP. Persistent high BB/9 is a red flag.",
      good: "<2.5", avg: "3.2", bad: ">4.0"
    },

    // ── Pitching Advanced ──
    "FIP": {
      name: "Fielding Independent Pitching",
      description: "ERA estimated from only K, BB, and HR — things a pitcher controls. The most important advanced pitching stat. When FIP << ERA, the pitcher has been unlucky. When FIP >> ERA, they've been lucky.",
      good: "<3.00", avg: "4.00", bad: ">5.00"
    },
    "xFIP": {
      name: "Expected FIP",
      description: "FIP with a league-average HR rate. Removes HR luck on top of BABIP luck. Even more stable than FIP for predicting future ERA. If HR/FB rate is abnormally high, xFIP will be lower than FIP.",
      good: "<3.20", avg: "4.00", bad: ">5.00"
    },
    "SIERA": {
      name: "Skill-Interactive ERA",
      description: "The most sophisticated ERA estimator — accounts for how K rate, BB rate, and ground ball rate interact. The single best predictor of future ERA among FIP, xFIP, and SIERA.",
      good: "<3.00", avg: "3.80", bad: ">4.50"
    },
    "K-BB%": {
      name: "Strikeout Minus Walk Rate",
      description: "The simplest measure of pitching dominance — the gap between K% and BB%. Bigger gap = more dominant. Has one of the strongest year-to-year correlations of any pitching metric.",
      good: "20%+", avg: "12%", bad: "<8%"
    },

    // ── Statcast ──
    "Avg EV": {
      name: "Average Exit Velocity",
      description: "Average speed off the bat in mph. The best single measure of how hard a hitter hits. Higher EV correlates strongly with more HR and higher SLG. If EV is elite but AVG is low, the hitter is likely getting unlucky.",
      good: "92+", avg: "88", bad: "<85"
    },
    "Avg Exit Velo": {
      name: "Average Exit Velocity",
      description: "Average speed off the bat in mph. The best single measure of how hard a hitter hits. Higher EV correlates strongly with more HR and higher SLG. If EV is elite but AVG is low, the hitter is likely getting unlucky.",
      good: "92+", avg: "88", bad: "<85"
    },
    "Max EV": {
      name: "Max Exit Velocity",
      description: "Hardest-hit ball of the season in mph. Shows absolute ceiling of power. Players who can hit 115+ mph have true elite raw power even if HR totals don't show it yet.",
      good: "112+", avg: "108", bad: "<104"
    },
    "Max Exit Velo": {
      name: "Max Exit Velocity",
      description: "Hardest-hit ball of the season in mph. Shows absolute ceiling of power. Players who can hit 115+ mph have true elite raw power even if HR totals don't show it yet.",
      good: "112+", avg: "108", bad: "<104"
    },
    "Barrel %": {
      name: "Barrel Rate",
      description: "Percentage of batted balls at the ideal combination of exit velocity (98+ mph) and launch angle (26–30°). The best predictor of HR power. A barreled ball averages .500+ AVG and 1.500+ SLG.",
      good: "12%+", avg: "7%", bad: "<4%"
    },
    "Barrel%": {
      name: "Barrel Rate",
      description: "Percentage of batted balls at the ideal combination of exit velocity (98+ mph) and launch angle (26–30°). The best predictor of HR power. A barreled ball averages .500+ AVG and 1.500+ SLG.",
      good: "12%+", avg: "7%", bad: "<4%"
    },
    "Hard Hit %": {
      name: "Hard Hit Rate",
      description: "Percentage of batted balls at 95+ mph exit velocity. Broader contact quality measure than Barrel%. Hard-hit balls become hits more often regardless of launch angle.",
      good: "45%+", avg: "38%", bad: "<30%"
    },
    "Hard Hit%": {
      name: "Hard Hit Rate",
      description: "Percentage of batted balls at 95+ mph exit velocity. Broader contact quality measure than Barrel%. Hard-hit balls become hits more often regardless of launch angle.",
      good: "45%+", avg: "38%", bad: "<30%"
    },
    "xBA": {
      name: "Expected Batting Average",
      description: "What AVG 'should be' based on exit velocity and launch angle, removing fielding and luck. When xBA >> actual AVG, the hitter has been unlucky and their average should rise.",
      good: ".280+", avg: ".250", bad: "<.220"
    },
    "xSLG": {
      name: "Expected Slugging",
      description: "What SLG 'should be' based on quality of contact. A big xSLG-SLG gap means the power numbers are coming — the hitter is making great contact that hasn't fully converted to extra-base hits yet.",
      good: ".500+", avg: ".420", bad: "<.350"
    },
    "xwOBA": {
      name: "Expected Weighted On-Base Average",
      description: "The most important Statcast metric. What wOBA 'should be' based on batted ball quality. The foundation of this app's Buy Low / Sell High signals. When xwOBA > wOBA, the player is better than their stats show.",
      good: ".370+", avg: ".320", bad: "<.290"
    },
    "Sweet Spot %": {
      name: "Sweet Spot Rate",
      description: "Percentage of batted balls at the optimal launch angle range (8–32°). Shows how consistently a hitter makes productive contact — fewer pop-ups and weak grounders.",
      good: "38%+", avg: "33%", bad: "<28%"
    },
    "Sweet Spot%": {
      name: "Sweet Spot Rate",
      description: "Percentage of batted balls at the optimal launch angle range (8–32°). Shows how consistently a hitter makes productive contact — fewer pop-ups and weak grounders.",
      good: "38%+", avg: "33%", bad: "<28%"
    },
    "Sprint Speed": {
      name: "Sprint Speed",
      description: "Top running speed in feet per second. Directly relevant for stolen base potential and infield hit probability. A fast player with low SB might just need the green light from their manager.",
      good: "28+", avg: "27", bad: "<26"
    },
    "Whiff %": {
      name: "Whiff Rate",
      description: "How often a hitter swings and misses. Lower is better — high whiff% means more strikeouts and lower AVG. Some elite sluggers compensate with extreme power on contact.",
      good: "<22%", avg: "25%", bad: ">30%"
    },
    "Whiff%": {
      name: "Whiff Rate",
      description: "How often a hitter swings and misses. Lower is better — high whiff% means more strikeouts and lower AVG. Some elite sluggers compensate with extreme power on contact.",
      good: "<22%", avg: "25%", bad: ">30%"
    },
    "Chase %": {
      name: "Chase Rate",
      description: "How often a hitter swings at pitches outside the strike zone. Lower is better — shows plate discipline. Low chase rate predicts sustainable walk rates and overall offensive consistency.",
      good: "<22%", avg: "28%", bad: ">33%"
    },
    "Chase%": {
      name: "Chase Rate",
      description: "How often a hitter swings at pitches outside the strike zone. Lower is better — shows plate discipline. Low chase rate predicts sustainable walk rates and overall offensive consistency.",
      good: "<22%", avg: "28%", bad: ">33%"
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
      description: "Projected rest-of-season fantasy points using this league's H2H Points scoring (SV=7, HLD=4, OUT=1.5, ER=-4, K=-0.5). Higher = more valuable. This is the primary ranking metric.",
      good: "300+", avg: "150", bad: "<75"
    },
    "actual_points": {
      name: "Actual Points",
      description: "Fantasy points earned so far this season using the league's scoring rules. Compare to projected points — if actual is much lower, the player may be underperforming (buy low).",
      good: "—", avg: "—", bad: "—"
    },
    "points_per_pa": {
      name: "Points per Plate Appearance",
      description: "Fantasy points per PA — the key efficiency metric for hitters. Accounts for positive (HR, BB, hits) and negative (K) contributions per trip to the plate. Higher is better. Contact hitters with high BB rates excel here.",
      good: "1.5+", avg: "1.0", bad: "<0.7"
    },
    "points_per_ip": {
      name: "Points per Inning Pitched",
      description: "Fantasy points per inning — shows pitching efficiency. Accounts for outs (1.5/out), K (0.5), and penalties (ER=-4, H=-0.75, BB=-0.75). Higher means the pitcher generates more points per inning.",
      good: "4.0+", avg: "2.5", bad: "<1.5"
    },
    "points_per_start": {
      name: "Points per Start",
      description: "Average fantasy points per game started. The single best metric for evaluating starting pitchers in this format. Elite aces average 20+. Streamers should project 8+ to be worth starting.",
      good: "20+", avg: "12", bad: "<8"
    },
    "points_per_appearance": {
      name: "Points per Appearance",
      description: "Average fantasy points per relief appearance. Closers with saves average 8+ (clean save = 12.5 pts). Setup men with holds average 5-7. This is how you evaluate relievers in H2H Points.",
      good: "8+", avg: "4", bad: "<2"
    },
    "surplus_value": {
      name: "Surplus Value (Points)",
      description: "Projected points above replacement level at the player's position. Replacement level = the projected points of the first player outside the roster-worthy pool at each position. The key metric for trade evaluation.",
      good: "100+", avg: "25", bad: "<0"
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
    <div id="info-tooltip-benchmarks" class="mt-2 grid grid-cols-3 gap-1 text-xs" style="display:none;">
      <span class="text-green-400" id="info-tooltip-good"></span>
      <span class="text-gray-400" id="info-tooltip-avg"></span>
      <span class="text-red-400" id="info-tooltip-bad"></span>
    </div>
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

  const benchmarks = document.getElementById("info-tooltip-benchmarks");
  if (data.good && data.good !== "—") {
    document.getElementById("info-tooltip-good").textContent = "Good: " + data.good;
    document.getElementById("info-tooltip-avg").textContent = "Avg: " + data.avg;
    document.getElementById("info-tooltip-bad").textContent = "Bad: " + data.bad;
    benchmarks.style.display = "grid";
  } else {
    benchmarks.style.display = "none";
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
