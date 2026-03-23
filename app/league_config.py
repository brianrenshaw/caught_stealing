"""League-specific configuration for H2H Points scoring.

This module defines the exact scoring rules, roster structure, and strategic
constants for the Galactic Empire Yahoo Fantasy Baseball league. Every
projection, ranking, and recommendation in the app optimizes for this format.
"""

# ── League Configuration ──

LEAGUE_CONFIG = {
    "league_name": "Galactic Empire",
    "league_id": 37132,
    "platform": "yahoo",
    "teams": 10,
    "scoring_type": "head_to_head_points",
    "keeper": True,
    "weekly_deadline": "monday",
    "trade_deadline": "2026-08-06",
    "playoffs": {
        "teams": 6,
        "start_week": 22,
        "end_week": 24,
        "end_date": "2026-09-13",
    },
    "roster_slots": {
        "C": 1,
        "1B": 1,
        "2B": 1,
        "3B": 1,
        "SS": 1,
        "OF": 3,
        "Util": 1,
        "SP": 2,
        "RP": 2,
        "P": 4,  # Flexible: can be SP or RP — critical strategic lever
        "BN": 4,
        "IL": 3,
        "NA": 1,
    },
    "batting_scoring": {
        "R": 1,
        "1B": 1,  # Singles
        "2B": 2,  # Doubles
        "3B": 3,  # Triples
        "HR": 4,  # Home Runs
        "RBI": 1,
        "SB": 2,
        "CS": -1,
        "BB": 1,
        "HBP": 1,
        "K": -0.5,  # Batter strikeouts
    },
    "pitching_scoring": {
        "OUT": 1.5,  # Per out recorded (IP = 4.5 points)
        "K": 0.5,  # Pitcher strikeouts
        "SV": 7,
        "HLD": 4,
        "RW": 4,  # Relief wins
        "QS": 2,  # Quality starts
        "CG": 1,  # Complete game
        "SHO": 1,  # Shutout
        "NH": 1,  # No-hitter
        "PG": 1,  # Perfect game
        "H": -0.75,  # Hits allowed
        "ER": -4,  # Earned runs
        "BB": -0.75,  # Walks issued
        "HBP": -0.75,  # Hit batters
    },
}

# ── Convenience Accessors ──

BATTING_SCORING = LEAGUE_CONFIG["batting_scoring"]
PITCHING_SCORING = LEAGUE_CONFIG["pitching_scoring"]
ROSTER_SLOTS = LEAGUE_CONFIG["roster_slots"]
NUM_TEAMS = LEAGUE_CONFIG["teams"]

# Total active roster slots
ACTIVE_HITTER_SLOTS = (
    ROSTER_SLOTS["C"]
    + ROSTER_SLOTS["1B"]
    + ROSTER_SLOTS["2B"]
    + ROSTER_SLOTS["3B"]
    + ROSTER_SLOTS["SS"]
    + ROSTER_SLOTS["OF"]
    + ROSTER_SLOTS["Util"]
)  # = 9
ACTIVE_PITCHER_SLOTS = (
    ROSTER_SLOTS["SP"] + ROSTER_SLOTS["RP"] + ROSTER_SLOTS["P"]
)  # = 8


# ── Strategic Scoring Insights ──
# These constants encode the key strategic implications of this scoring system.
# They drive recommendation thresholds throughout the app.


# 1. RELIEVER VALUE IS EXTREME
# SV=7, HLD=4, RW=4. A dominant closer who pitches 1 clean inning with 2 Ks
# and a save earns: 3*1.5 + 2*0.5 + 7 = 12.5 points in one appearance.
# Elite closers and high-leverage relievers are PREMIUM assets.
ELITE_CLOSER_SAVE_POINTS = 12.5  # Clean 1 IP, 2K, save
ELITE_SETUP_HOLD_POINTS = 9.5  # Clean 1 IP, 2K, hold
RELIEVER_BLOWUP_POINTS = -5.25  # 1 IP, 3H, 2ER, blown save

# 2. INNINGS ARE GOLD FOR STARTERS
# Each IP = 4.5 points from outs. A 7-IP start = 31.5 from outs alone.
# Innings-eating starters with low ERAs are the most valuable pitchers.
POINTS_PER_INNING = 4.5  # 3 outs * 1.5
POINTS_PER_OUT = 1.5
ELITE_START_EXAMPLE = 24.5  # 7 IP, 7K, 2ER, 5H, 1BB, QS
MEDIOCRE_START_EXAMPLE = 1.5  # 5 IP, 5K, 4ER, 7H, 3BB

# 3. EARNED RUNS ARE DEVASTATING
# At -4 per ER, a 5-ER blowup costs 20 points from ER alone.
# Avoid volatile starters. Prefer consistency over upside.
ER_PENALTY = -4.0
BLOWUP_THRESHOLD_ER = 5  # 5+ ER = devastating start

# 4. CONTACT HITTERS HAVE AN EDGE
# K = -0.5. A 150-K player loses 75 pts from Ks; an 80-K player loses 40.
# The 35-pt gap means contact hitters can outscore TTO sluggers.
# Break-even: 1 HR (~4 pts) offsets ~8 extra Ks (8 * 0.5 = 4 pts).
K_PENALTY = -0.5
HR_TO_K_BREAKEVEN_RATIO = 8  # 1 HR offsets 8 extra strikeouts

# 5. STOLEN BASES ARE EFFICIENTLY PRICED
# SB=2, CS=-1. Break-even success rate = 33%. Real stealers succeed 70-80%.
# At 75% success: EV per attempt = 0.75*2 + 0.25*(-1) = 1.25 pts.
SB_BREAKEVEN_PCT = 0.333
SB_EV_AT_75_PCT = 1.25  # Expected value per steal attempt at 75% success

# 6. WALKS AND HBP ARE FREE POINTS
# BB=1, HBP=1. High-OBP / low-K hitters are systematically undervalued.
# An 80-BB player earns 80 points from walks alone.
BB_VALUE = 1.0
HBP_VALUE = 1.0

# 7. THE P SLOT FLEXIBILITY IS A STRATEGIC LEVER
# 4 P slots can be SP or RP. Optimal allocation varies by week:
# - Heavy SP weeks: fill P slots with starters for volume points
# - Light SP weeks: load up on RP for saves/holds
P_SLOT_COUNT = 4


# ── Replacement Level Thresholds ──
# Replacement level = projected points of the (slots * teams + 1)th player.
# Used for surplus value calculations.

REPLACEMENT_LEVEL_SLOTS = {
    "C": NUM_TEAMS * 1,  # 10
    "1B": NUM_TEAMS * 1,  # 10
    "2B": NUM_TEAMS * 1,  # 10
    "3B": NUM_TEAMS * 1,  # 10
    "SS": NUM_TEAMS * 1,  # 10
    "OF": NUM_TEAMS * 3,  # 30
    "Util": NUM_TEAMS * 1,  # 10 (best available any position)
    "SP": NUM_TEAMS * 2,  # 20 (dedicated SP slots only)
    "RP": NUM_TEAMS * 2,  # 20 (dedicated RP slots only)
}


# ── Start Projection Thresholds ──
# Used by the per-start projection model for recommendations.

START_THRESHOLD_MUST_START = 20.0  # Ace-level projection
START_THRESHOLD_START = 12.0  # Solid starter
START_THRESHOLD_STREAM = 8.0  # Acceptable streaming option
START_THRESHOLD_SIT = 0.0  # Likely net-positive but risky
# Below 0 = AVOID (projected net-negative)

# ── Reliever Recommendation Tiers ──

RELIEVER_TIER_ELITE_CLOSER = "elite_closer"  # Top 10 closer, must roster
RELIEVER_TIER_STRONG_CLOSER = "strong_closer"  # Top 20 closer, strong hold
RELIEVER_TIER_HOLDS_MACHINE = "holds_machine"  # 3+ holds/week opportunity
RELIEVER_TIER_STREAMING_RP = "streaming_rp"  # Good per-appearance, stream
RELIEVER_TIER_AVOID = "avoid"  # Volatile or low-opportunity

# ── Dashboard Color Thresholds ──
# Points thresholds for color-coding on the dashboard.

# Hitters: points per game
HITTER_GREEN_THRESHOLD = 5.0
HITTER_YELLOW_THRESHOLD = 3.0
# Below yellow = red

# SP per start
SP_GREEN_THRESHOLD = 15.0
SP_YELLOW_THRESHOLD = 8.0
SP_ORANGE_THRESHOLD = 0.0
# Below 0 = dark red (AVOID)

# RP per appearance
RP_GREEN_THRESHOLD = 8.0
RP_YELLOW_THRESHOLD = 4.0
# Below yellow = red

# Streaming recommendation minimum
STREAM_MIN_PROJECTED_POINTS = 8.0  # Only recommend streamers above this
