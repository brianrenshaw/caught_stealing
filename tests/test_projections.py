"""Test projection engine math and signal detection."""

import pytest

from app.services.projection_service import (
    SIGNAL_THRESHOLD,
    _calc_confidence,
    _weighted_avg,
    project_hitter,
    project_pitcher,
)
from tests.conftest import (
    make_batting_stats,
    make_pitching_stats,
    make_player,
    make_statcast_summary,
)


class TestWeightedAverage:
    def test_all_values_present(self):
        result = _weighted_avg([(10.0, 0.5), (20.0, 0.5)])
        assert result == 15.0

    def test_none_values_skipped(self):
        result = _weighted_avg([(10.0, 0.5), (None, 0.5)])
        assert result == 10.0

    def test_all_none_returns_none(self):
        result = _weighted_avg([(None, 0.5), (None, 0.5)])
        assert result is None

    def test_single_value(self):
        result = _weighted_avg([(42.0, 1.0)])
        assert result == 42.0

    def test_unequal_weights(self):
        result = _weighted_avg([(10.0, 0.75), (20.0, 0.25)])
        assert abs(result - 12.5) < 0.001


class TestConfidenceScore:
    def test_zero_pa(self):
        score = _calc_confidence(0, False, 0.0)
        assert score == 0.1

    def test_none_pa(self):
        score = _calc_confidence(None, False, 0.0)
        assert score == 0.1

    def test_high_pa_with_statcast(self):
        score = _calc_confidence(500, True, 0.8)
        assert score > 0.7

    def test_low_pa_no_statcast(self):
        score = _calc_confidence(60, False, 0.1)
        assert score < 0.3

    def test_max_confidence_capped_at_1(self):
        score = _calc_confidence(1000, True, 1.0)
        assert score <= 1.0


@pytest.mark.asyncio
class TestHitterProjection:
    async def test_basic_hitter_projection(self, session):
        player = make_player(name="Aaron Judge", position="OF")
        session.add(player)
        await session.flush()

        batting = make_batting_stats(
            player.id,
            pa=450,
            hr=35,
            r=75,
            rbi=80,
            sb=5,
            avg=0.290,
            obp=0.390,
            slg=0.580,
            ops=0.970,
            woba=0.400,
        )
        session.add(batting)

        statcast = make_statcast_summary(
            player.id,
            xba=0.295,
            xslg=0.590,
            xwoba=0.410,
        )
        session.add(statcast)
        await session.flush()

        proj = await project_hitter(session, player, 2026)
        assert proj is not None
        assert proj.player_name == "Aaron Judge"
        assert proj.projected_hr > 35  # Should project remaining HR
        assert proj.projected_avg > 0  # Should have a valid avg projection
        assert proj.confidence_score > 0

    async def test_hitter_below_min_pa_excluded(self, session):
        player = make_player(name="Low PA Guy")
        session.add(player)
        await session.flush()

        batting = make_batting_stats(player.id, pa=30)  # Below 50 PA minimum
        session.add(batting)
        await session.flush()

        proj = await project_hitter(session, player, 2026)
        assert proj is None

    async def test_buy_low_signal(self, session):
        """When xwOBA exceeds wOBA by >= .030, should flag buy low."""
        player = make_player(name="Buy Low Guy")
        session.add(player)
        await session.flush()

        batting = make_batting_stats(player.id, woba=0.300)
        session.add(batting)

        # xwOBA much higher than actual wOBA
        statcast = make_statcast_summary(player.id, xwoba=0.340)
        session.add(statcast)
        await session.flush()

        proj = await project_hitter(session, player, 2026)
        assert proj is not None
        assert proj.buy_low_signal is True
        assert proj.xwoba_delta >= SIGNAL_THRESHOLD

    async def test_sell_high_signal(self, session):
        """When actual wOBA exceeds xwOBA by >= .030, should flag sell high."""
        player = make_player(name="Sell High Guy")
        session.add(player)
        await session.flush()

        batting = make_batting_stats(player.id, woba=0.370)
        session.add(batting)

        statcast = make_statcast_summary(player.id, xwoba=0.330)
        session.add(statcast)
        await session.flush()

        proj = await project_hitter(session, player, 2026)
        assert proj is not None
        assert proj.sell_high_signal is True
        assert proj.xwoba_delta <= -SIGNAL_THRESHOLD


@pytest.mark.asyncio
class TestPitcherProjection:
    async def test_basic_pitcher_projection(self, session):
        player = make_player(name="Gerrit Cole", position="SP")
        session.add(player)
        await session.flush()

        pitching = make_pitching_stats(
            player.id,
            ip=150,
            w=10,
            sv=0,
            so=180,
            era=3.00,
            whip=1.05,
            k_per_9=10.8,
            fip=2.90,
            xfip=3.00,
        )
        session.add(pitching)
        await session.flush()

        proj = await project_pitcher(session, player, 2026)
        assert proj is not None
        assert proj.player_name == "Gerrit Cole"
        assert proj.projected_w > 10  # Should project remaining wins
        assert proj.projected_k > 180  # Should project remaining K
        assert proj.projected_era > 0
        assert proj.projected_era < 5  # Should be reasonable
        assert proj.projected_whip > 0

    async def test_closer_projects_saves(self, session):
        player = make_player(name="Edwin Diaz", position="RP")
        session.add(player)
        await session.flush()

        pitching = make_pitching_stats(
            player.id,
            ip=45,
            w=3,
            sv=25,
            so=60,
            era=2.50,
            whip=0.95,
            k_per_9=12.0,
            fip=2.30,
            xfip=2.50,
            g=45,
            gs=0,
        )
        session.add(pitching)
        await session.flush()

        proj = await project_pitcher(session, player, 2026)
        assert proj is not None
        assert proj.projected_sv > 25  # Should project remaining saves

    async def test_pitcher_below_min_ip_excluded(self, session):
        player = make_player(name="Low IP Guy", position="SP")
        session.add(player)
        await session.flush()

        pitching = make_pitching_stats(player.id, ip=10)  # Below 20 IP minimum
        session.add(pitching)
        await session.flush()

        proj = await project_pitcher(session, player, 2026)
        assert proj is None
