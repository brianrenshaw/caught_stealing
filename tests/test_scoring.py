"""Tests for the H2H Points scoring system.

All expected values are hand-calculated from the Galactic Empire league rules:
  Batting: R=1, 1B=1, 2B=2, 3B=3, HR=4, RBI=1, SB=2, CS=-1, BB=1, HBP=1, K=-0.5
  Pitching: OUT=1.5, K=0.5, SV=7, HLD=4, RW=4, QS=2, CG=1, SHO=1, NH=1, PG=1,
            H=-0.75, ER=-4, BB=-0.75, HBP=-0.75
"""

import pytest

from app.services.points_service import (
    _ip_to_outs,
    calculate_batter_points,
    calculate_pitcher_points,
    calculate_points_per_appearance,
    calculate_points_per_pa,
    calculate_points_per_start,
    get_points_breakdown,
)

# ── IP to Outs Conversion ──


class TestIPToOuts:
    def test_whole_innings(self):
        assert _ip_to_outs(7.0) == 21

    def test_one_third(self):
        assert _ip_to_outs(6.1) == 19

    def test_two_thirds(self):
        assert _ip_to_outs(6.2) == 20

    def test_zero(self):
        assert _ip_to_outs(0) == 0

    def test_none(self):
        assert _ip_to_outs(None) == 0

    def test_one_inning(self):
        assert _ip_to_outs(1.0) == 3

    def test_three_innings_one_out(self):
        assert _ip_to_outs(3.1) == 10


# ── Batter Points Calculation ──


class TestBatterPoints:
    def test_batter_game_with_hr(self):
        """Test: 1R, 1HR, 2RBI, 1BB, 1K = 7.5 pts.

        R: 1*1 = 1
        HR: 1*4 = 4  (HR is NOT also counted as a single)
        RBI: 2*1 = 2
        BB: 1*1 = 1
        K: 1*-0.5 = -0.5
        Total: 7.5
        """
        stats = {"R": 1, "HR": 1, "RBI": 2, "BB": 1, "K": 1, "H": 1, "2B": 0, "3B": 0}
        assert calculate_batter_points(stats) == 7.5

    def test_singles_derived_from_hits(self):
        """When 1B not provided, derive: 1B = H - 2B - 3B - HR."""
        stats = {"H": 3, "2B": 1, "3B": 0, "HR": 1}
        # 1B = 3 - 1 - 0 - 1 = 1
        # Points: 1B*1 + 2B*2 + HR*4 = 1 + 2 + 4 = 7
        assert calculate_batter_points(stats) == 7.0

    def test_explicit_singles(self):
        """When 1B is provided directly, use it."""
        stats = {"1B": 2, "2B": 1, "HR": 0}
        # Points: 2*1 + 1*2 = 4
        assert calculate_batter_points(stats) == 4.0

    def test_full_game_contact_hitter(self):
        """Contact hitter: 2 H (2 singles), 1 R, 1 RBI, 1 BB, 0 K."""
        stats = {"H": 2, "2B": 0, "3B": 0, "HR": 0, "R": 1, "RBI": 1, "BB": 1, "K": 0}
        # 1B=2*1=2, R=1, RBI=1, BB=1 = 5.0
        assert calculate_batter_points(stats) == 5.0

    def test_tto_slugger(self):
        """TTO slugger: 1 HR, 1 R, 1 RBI, 1 BB, 3 K."""
        stats = {"H": 1, "2B": 0, "3B": 0, "HR": 1, "R": 1, "RBI": 1, "BB": 1, "K": 3}
        # HR=4, R=1, RBI=1, BB=1, K=3*-0.5=-1.5 = 5.5
        assert calculate_batter_points(stats) == 5.5

    def test_stolen_base_value(self):
        """SB=2, CS=-1."""
        stats = {"SB": 1, "CS": 0}
        assert calculate_batter_points(stats) == 2.0
        stats_cs = {"SB": 1, "CS": 1}
        assert calculate_batter_points(stats_cs) == 1.0  # 2 + -1

    def test_hbp_value(self):
        """HBP = 1 point."""
        stats = {"HBP": 1}
        assert calculate_batter_points(stats) == 1.0

    def test_zero_stat_line(self):
        """0-for-4 with 2 K = -1.0."""
        stats = {"H": 0, "2B": 0, "3B": 0, "HR": 0, "K": 2}
        assert calculate_batter_points(stats) == -1.0

    def test_so_alias(self):
        """SO should work as alias for K."""
        stats = {"SO": 3}
        assert calculate_batter_points(stats) == -1.5

    def test_triple(self):
        """Triple = 3 points."""
        stats = {"H": 1, "2B": 0, "3B": 1, "HR": 0}
        # 1B = 1-0-1-0 = 0, 3B = 3
        assert calculate_batter_points(stats) == 3.0


# ── Pitcher Points Calculation ──


class TestPitcherPoints:
    def test_elite_start(self):
        """Elite start: 7 IP, 7K, 2ER, 5H, 1BB, QS.

        Outs: 21 * 1.5 = 31.5
        K: 7 * 0.5 = 3.5
        QS: 1 * 2 = 2
        H: 5 * -0.75 = -3.75
        ER: 2 * -4 = -8
        BB: 1 * -0.75 = -0.75
        Total: 24.5
        """
        stats = {"IP": 7, "K": 7, "ER": 2, "H": 5, "BB": 1, "QS": 1}
        assert calculate_pitcher_points(stats) == 24.5

    def test_closer_save(self):
        """Closer save: 1 IP, 2K, 0H, 0ER, 0BB, SV.

        Outs: 3 * 1.5 = 4.5
        K: 2 * 0.5 = 1.0
        SV: 1 * 7 = 7.0
        Total: 12.5
        """
        stats = {"IP": 1, "K": 2, "H": 0, "ER": 0, "BB": 0, "SV": 1}
        assert calculate_pitcher_points(stats) == 12.5

    def test_blowup_start(self):
        """Blowup: 3 IP, 2K, 6ER, 8H, 3BB.

        Outs: 9 * 1.5 = 13.5
        K: 2 * 0.5 = 1.0
        ER: 6 * -4 = -24
        H: 8 * -0.75 = -6.0
        BB: 3 * -0.75 = -2.25
        Total: -17.75
        """
        stats = {"IP": 3, "K": 2, "ER": 6, "H": 8, "BB": 3}
        assert calculate_pitcher_points(stats) == -17.75

    def test_mediocre_start(self):
        """Mediocre: 5 IP, 5K, 4ER, 7H, 3BB.

        Outs: 15 * 1.5 = 22.5
        K: 5 * 0.5 = 2.5
        ER: 4 * -4 = -16
        H: 7 * -0.75 = -5.25
        BB: 3 * -0.75 = -2.25
        Total: 1.5
        """
        stats = {"IP": 5, "K": 5, "ER": 4, "H": 7, "BB": 3}
        assert calculate_pitcher_points(stats) == 1.5

    def test_hold(self):
        """Setup man hold: 1 IP, 2K, 0H, 0ER, 0BB, HLD.

        Outs: 3 * 1.5 = 4.5
        K: 2 * 0.5 = 1.0
        HLD: 1 * 4 = 4.0
        Total: 9.5
        """
        stats = {"IP": 1, "K": 2, "H": 0, "ER": 0, "BB": 0, "HLD": 1}
        assert calculate_pitcher_points(stats) == 9.5

    def test_relief_win(self):
        """Reliever win: 1 IP, 1K, 0H, 0ER, 0BB, W=1.

        Outs: 3 * 1.5 = 4.5
        K: 1 * 0.5 = 0.5
        RW: 1 * 4 = 4.0
        Total: 9.0
        """
        stats = {"IP": 1, "K": 1, "H": 0, "ER": 0, "BB": 0, "W": 1}
        result = calculate_pitcher_points(stats, is_reliever=True)
        assert result == 9.0

    def test_relief_win_not_counted_for_starters(self):
        """Starters don't get RW points."""
        stats = {"IP": 7, "K": 5, "H": 6, "ER": 3, "BB": 2, "W": 1}
        # Starter: no RW
        starter_pts = calculate_pitcher_points(stats, is_reliever=False)
        # Reliever: +4 for RW
        reliever_pts = calculate_pitcher_points(stats, is_reliever=True)
        assert reliever_pts - starter_pts == 4.0

    def test_fractional_ip(self):
        """6.2 IP = 20 outs = 30 points from outs."""
        stats = {"IP": 6.2, "K": 0, "H": 0, "ER": 0, "BB": 0}
        assert calculate_pitcher_points(stats) == 30.0  # 20 * 1.5

    def test_hbp_penalty(self):
        """HBP = -0.75 per hit batter."""
        stats = {"IP": 1, "K": 0, "H": 0, "ER": 0, "BB": 0, "HBP": 2}
        # Outs: 4.5, HBP: 2*-0.75 = -1.5 → 3.0
        assert calculate_pitcher_points(stats) == 3.0

    def test_complete_game_shutout(self):
        """CG shutout: 9 IP, 10K, 0ER, 4H, 1BB, QS, CG, SHO.

        Outs: 27*1.5=40.5, K: 10*0.5=5, QS=2, CG=1, SHO=1, H: 4*-0.75=-3, BB: -0.75
        Total: 45.75
        """
        stats = {"IP": 9, "K": 10, "ER": 0, "H": 4, "BB": 1, "QS": 1, "CG": 1, "SHO": 1}
        assert calculate_pitcher_points(stats) == 45.75

    def test_blown_save(self):
        """Blown save: 0.2 IP, 0K, 3H, 2ER, 1BB (no save).

        Outs: 2*1.5=3, H: 3*-0.75=-2.25, ER: 2*-4=-8, BB: -0.75
        Total: -8.0
        """
        stats = {"IP": 0.2, "K": 0, "H": 3, "ER": 2, "BB": 1, "SV": 0}
        assert calculate_pitcher_points(stats) == -8.0

    def test_so_alias_pitcher(self):
        """SO should work as alias for K in pitching too."""
        stats = {"IP": 1, "SO": 2, "H": 0, "ER": 0, "BB": 0}
        assert calculate_pitcher_points(stats) == 5.5  # 4.5 + 1.0


# ── Rate Stat Functions ──


class TestRateStats:
    def test_points_per_pa(self):
        stats = {"PA": 4, "H": 2, "2B": 0, "3B": 0, "HR": 1, "R": 1, "RBI": 2, "BB": 0, "K": 1}
        # 1B=1*1=1, HR=1*4=4, R=1, RBI=2, K=-0.5 → 7.5
        # 7.5 / 4 PA = 1.875
        result = calculate_points_per_pa(stats)
        assert result == pytest.approx(1.875)

    def test_points_per_pa_zero_pa(self):
        assert calculate_points_per_pa({"PA": 0}) == 0.0

    def test_points_per_start(self):
        stats = {
            "IP": 14,
            "GS": 2,
            "K": 14,
            "ER": 4,
            "H": 10,
            "BB": 2,
            "QS": 2,
        }
        # Outs: 42*1.5=63, K: 14*0.5=7, QS: 2*2=4, H: 10*-0.75=-7.5, ER: 4*-4=-16, BB: 2*-0.75=-1.5
        # Total: 49, per start: 49/2 = 24.5
        result = calculate_points_per_start(stats)
        assert result == pytest.approx(24.5)

    def test_points_per_appearance_reliever(self):
        stats = {
            "IP": 10,
            "G": 10,
            "K": 12,
            "ER": 2,
            "H": 6,
            "BB": 3,
            "SV": 5,
            "HLD": 2,
        }
        # Outs: 30*1.5=45, K: 12*0.5=6, SV: 5*7=35, HLD: 2*4=8
        # H: 6*-0.75=-4.5, ER: 2*-4=-8, BB: 3*-0.75=-2.25
        # Total: 79.25, per appearance: 7.925
        result = calculate_points_per_appearance(stats, is_reliever=True)
        assert result == pytest.approx(7.925)


# ── Points Breakdown ──


class TestPointsBreakdown:
    def test_pitcher_breakdown(self):
        stats = {"IP": 7, "K": 7, "ER": 2, "H": 5, "BB": 1, "QS": 1}
        breakdown = get_points_breakdown(stats, is_pitcher=True)
        assert breakdown["outs"] == 31.5
        assert breakdown["k"] == 3.5
        assert breakdown["qs"] == 2.0
        assert breakdown["h"] == -3.75
        assert breakdown["er"] == -8.0
        assert breakdown["bb"] == -0.75
        assert breakdown["total"] == 24.5

    def test_batter_breakdown(self):
        stats = {"R": 1, "HR": 1, "RBI": 2, "BB": 1, "K": 1, "H": 1, "2B": 0, "3B": 0}
        breakdown = get_points_breakdown(stats, is_pitcher=False)
        assert breakdown["hr"] == 4.0
        assert breakdown["r"] == 1.0
        assert breakdown["rbi"] == 2.0
        assert breakdown["bb"] == 1.0
        assert breakdown["k"] == -0.5
        assert breakdown["total"] == 7.5


# ── Season-Level Scenarios ──


class TestSeasonScenarios:
    def test_closer_season_points(self):
        """Elite closer: 35 SV, 65 IP, 2.50 ERA, 80K, ~55H, ~18 ER, ~20 BB.

        Outs: 195*1.5 = 292.5
        K: 80*0.5 = 40
        SV: 35*7 = 245
        H: 55*-0.75 = -41.25
        ER: 18*-4 = -72 (ERA 2.50 * 65 IP / 9 ≈ 18.06)
        BB: 20*-0.75 = -15
        Total ≈ 449.25
        """
        stats = {
            "IP": 65,
            "K": 80,
            "SV": 35,
            "H": 55,
            "ER": 18,
            "BB": 20,
            "W": 3,
        }
        pts = calculate_pitcher_points(stats, is_reliever=True)
        # With RW: 3*4 = 12 extra
        # Outs: 195*1.5=292.5, K: 40, SV: 245, RW: 12, H: -41.25, ER: -72, BB: -15
        assert pts == pytest.approx(461.25)

    def test_setup_man_season(self):
        """Setup man: 25 HLD, 60 IP, 3.00 ERA, 70K, 50H, 20 ER, 18 BB."""
        stats = {
            "IP": 60,
            "K": 70,
            "HLD": 25,
            "H": 50,
            "ER": 20,
            "BB": 18,
            "W": 4,
        }
        pts = calculate_pitcher_points(stats, is_reliever=True)
        # Outs: 180*1.5=270, K: 35, HLD: 100, RW: 16
        # H: -37.5, ER: -80, BB: -13.5
        assert pts == pytest.approx(290.0)

    def test_contact_vs_power_hitter(self):
        """Compare contact hitter vs TTO slugger over a season.

        Contact: .290 AVG, 15 HR, 90 R, 75 RBI, 15 SB, 60 BB, 80 K, 5 CS
                 H=170, 2B=35, 3B=5, 1B=115
        TTO: .230 AVG, 35 HR, 85 R, 95 RBI, 3 SB, 75 BB, 170 K, 1 CS
             H=135, 2B=25, 3B=2, 1B=73
        """
        contact = {
            "R": 90, "H": 170, "2B": 35, "3B": 5, "HR": 15,
            "RBI": 75, "SB": 15, "CS": 5, "BB": 60, "HBP": 5, "K": 80,
        }
        tto = {
            "R": 85, "H": 135, "2B": 25, "3B": 2, "HR": 35,
            "RBI": 95, "SB": 3, "CS": 1, "BB": 75, "HBP": 3, "K": 170,
        }
        contact_pts = calculate_batter_points(contact)
        tto_pts = calculate_batter_points(tto)

        # Contact: R=90, 1B=115, 2B=70, 3B=15, HR=60, RBI=75, SB=30, CS=-5, BB=60, HBP=5, K=-40
        # = 475
        assert contact_pts == pytest.approx(475.0)

        # TTO: R=85, 1B=73, 2B=50, 3B=6, HR=140, RBI=95, SB=6, CS=-1, BB=75, HBP=3, K=-85
        # = 447
        assert tto_pts == pytest.approx(447.0)

        # In this scoring, the contact hitter wins by 28 points
        assert contact_pts > tto_pts
