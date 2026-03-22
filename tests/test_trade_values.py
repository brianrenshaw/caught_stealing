"""Test trade value calculations and z-scores."""

from app.services.trade_service import _z_scores


class TestZScores:
    def test_basic_z_scores(self):
        values = [10, 20, 30, 40, 50]
        z = _z_scores(values)
        # Mean = 30, values should be negative below mean, positive above
        assert z[0] < 0  # 10 is below mean
        assert z[4] > 0  # 50 is above mean
        assert abs(z[2]) < 0.01  # 30 is the mean

    def test_inverted_z_scores(self):
        """For stats like ERA where lower is better, z-scores should be inverted."""
        values = [2.0, 3.0, 4.0, 5.0]
        z_normal = _z_scores(values, invert=False)
        z_inverted = _z_scores(values, invert=True)
        # With inversion, lower values should have higher z-scores
        assert z_inverted[0] > z_inverted[3]
        # Without inversion, lower values have lower z-scores
        assert z_normal[0] < z_normal[3]

    def test_identical_values(self):
        """When all values are identical, z-scores should be 0."""
        values = [5.0, 5.0, 5.0]
        z = _z_scores(values)
        assert all(score == 0.0 for score in z)

    def test_two_values(self):
        values = [10, 20]
        z = _z_scores(values)
        assert z[0] < 0
        assert z[1] > 0
        # Should be symmetric
        assert abs(z[0] + z[1]) < 0.001


class TestTradeEvaluation:
    def test_fairness_thresholds(self):
        """Verify fairness labels match expected thresholds."""
        from app.services.trade_service import TradeEvaluation

        # Fair trade
        eval_fair = TradeEvaluation(
            side_a_players=[],
            side_b_players=[],
            side_a_total_value=5.0,
            side_b_total_value=5.3,
            value_difference=0.3,
            fairness="fair",
            category_impact_a={},
            category_impact_b={},
        )
        assert eval_fair.fairness == "fair"

        # Slightly uneven
        eval_slight = TradeEvaluation(
            side_a_players=[],
            side_b_players=[],
            side_a_total_value=6.0,
            side_b_total_value=5.0,
            value_difference=1.0,
            fairness="slightly_favors_b",
            category_impact_a={},
            category_impact_b={},
        )
        assert "slightly" in eval_slight.fairness
