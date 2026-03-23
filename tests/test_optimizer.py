"""Test lineup optimizer logic."""

from app.services.optimizer_service import _get_player_positions, _is_eligible


class TestPositionEligibility:
    def test_parse_single_position(self):
        assert _get_player_positions("SS") == ["SS"]

    def test_parse_multiple_positions(self):
        positions = _get_player_positions("2B, SS")
        assert "2B" in positions
        assert "SS" in positions

    def test_parse_none(self):
        assert _get_player_positions(None) == []

    def test_eligible_for_exact_position(self):
        assert _is_eligible(["SS"], "SS") is True

    def test_eligible_for_util(self):
        assert _is_eligible(["3B"], "Util") is True

    def test_not_eligible_wrong_position(self):
        assert _is_eligible(["SS"], "C") is False

    def test_of_eligible_for_of_slot(self):
        assert _is_eligible(["OF"], "OF") is True
        assert _is_eligible(["LF"], "OF") is True
        assert _is_eligible(["CF"], "OF") is True
        assert _is_eligible(["RF"], "OF") is True

    def test_pitcher_not_eligible_for_util(self):
        assert _is_eligible(["SP"], "Util") is False

    def test_pitcher_eligible_for_p_slot(self):
        assert _is_eligible(["SP"], "P") is True
        assert _is_eligible(["RP"], "P") is True

    def test_multi_position_eligible(self):
        assert _is_eligible(["2B", "SS"], "SS") is True
        assert _is_eligible(["2B", "SS"], "2B") is True
        assert _is_eligible(["2B", "SS"], "Util") is True
