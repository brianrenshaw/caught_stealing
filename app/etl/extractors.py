"""Extract data from Yahoo Fantasy API."""

import logging

from app.services.yahoo_service import yahoo_service

logger = logging.getLogger(__name__)


def _safe_int(val, default: int = 0) -> int:
    """Safely convert a value to int, returning default if None or invalid."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _safe_float(val, default: float = 0.0) -> float:
    """Safely convert a value to float, returning default if None or invalid."""
    if val is None:
        return default
    if isinstance(val, str) and val.strip() in ("", "-"):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_str(val, default: str = "") -> str:
    """Safely convert a value to str, decoding bytes if needed."""
    if val is None:
        return default
    if isinstance(val, bytes):
        return val.decode("utf-8")
    return str(val)


class YahooExtractor:
    """Pulls raw data from Yahoo Fantasy API and normalizes into plain dicts."""

    async def extract_stat_categories(self) -> dict[int, dict]:
        """Fetch league stat category definitions.

        Returns a mapping of stat_id -> {display_name, abbr, position_type}.
        This is needed to interpret player stats from Yahoo, which only include stat_id + value.
        """
        logger.info("Extracting stat categories from league settings...")
        settings = await yahoo_service.get_league_settings()
        categories = {}
        if hasattr(settings, "stat_categories") and hasattr(settings.stat_categories, "stats"):
            for stat in settings.stat_categories.stats:
                stat_id = getattr(stat, "stat_id", None)
                if stat_id is not None:
                    categories[_safe_int(stat_id)] = {
                        "display_name": _safe_str(getattr(stat, "display_name", "")),
                        "abbr": _safe_str(getattr(stat, "abbr", "")),
                        "position_type": _safe_str(getattr(stat, "position_type", "")),
                        "sort_order": _safe_int(getattr(stat, "sort_order", 1), 1),
                    }
        logger.info(f"Extracted {len(categories)} stat categories")
        return categories

    async def extract_standings(self) -> list[dict]:
        """Fetch league standings.

        Returns a list of team dicts with rank, name, record, and points.
        """
        logger.info("Extracting league standings...")
        standings = await yahoo_service.get_league_standings()
        teams = []
        if hasattr(standings, "teams"):
            for team in standings.teams:
                name = _safe_str(getattr(team, "name", "Unknown"), "Unknown")

                team_standings = getattr(team, "team_standings", None)
                wins = 0
                losses = 0
                ties = 0
                rank = 0
                points_for = 0.0
                points_against = 0.0

                if team_standings:
                    rank = _safe_int(getattr(team_standings, "rank", 0))
                    outcome_totals = getattr(team_standings, "outcome_totals", None)
                    if outcome_totals:
                        wins = _safe_int(getattr(outcome_totals, "wins", 0))
                        losses = _safe_int(getattr(outcome_totals, "losses", 0))
                        ties = _safe_int(getattr(outcome_totals, "ties", 0))
                    points_for = _safe_float(getattr(team_standings, "points_for", 0))
                    points_against = _safe_float(getattr(team_standings, "points_against", 0))

                teams.append(
                    {
                        "team_id": str(getattr(team, "team_id", "") or ""),
                        "name": name,
                        "rank": rank,
                        "wins": wins,
                        "losses": losses,
                        "ties": ties,
                        "points_for": points_for,
                        "points_against": points_against,
                        "is_owned_by_current_login": _safe_int(
                            getattr(team, "is_owned_by_current_login", 0)
                        )
                        == 1,
                    }
                )

        teams.sort(key=lambda t: t["rank"])
        logger.info(f"Extracted standings for {len(teams)} teams")
        return teams

    async def extract_all_rosters(self) -> dict[str, dict]:
        """Fetch rosters for all teams.

        Returns dict of team_id -> {team_name, team_id, is_my_team, players: [dict]}.
        """
        logger.info("Extracting rosters for all teams...")
        raw_rosters = await yahoo_service.get_all_team_rosters()
        result = {}

        for team_id, team_data in raw_rosters.items():
            players = []
            for player in team_data.get("players", []):
                player_dict = self._extract_player(player)
                if player_dict:
                    players.append(player_dict)

            result[team_id] = {
                "team_id": team_id,
                "team_name": team_data.get("team_name", "Unknown"),
                "is_my_team": _safe_int(team_data.get("is_owned_by_current_login", 0)) == 1,
                "players": players,
            }

        total_players = sum(len(r["players"]) for r in result.values())
        logger.info(f"Extracted {total_players} players across {len(result)} teams")
        return result

    async def extract_transactions(self, limit: int = 5) -> list[dict]:
        """Fetch recent league transactions."""
        logger.info(f"Extracting last {limit} transactions...")
        raw_transactions = await yahoo_service.get_league_transactions(limit=limit)
        transactions = []

        for txn in raw_transactions:
            txn_type = _safe_str(getattr(txn, "type", "unknown"), "unknown")
            timestamp = getattr(txn, "timestamp", None)
            status = _safe_str(getattr(txn, "status", ""))

            # Extract player names from transaction
            player_names = []
            txn_players = getattr(txn, "players", None) or []
            if txn_players:
                for p in txn_players:
                    name = _safe_str(getattr(p, "full_name", ""))
                    if not name:
                        name = _safe_str(getattr(p, "name", ""))
                    if name:
                        player_names.append(name)

            trader = _safe_str(getattr(txn, "trader_team_name", ""))
            tradee = _safe_str(getattr(txn, "tradee_team_name", ""))

            transactions.append(
                {
                    "type": txn_type,
                    "timestamp": _safe_int(timestamp) if timestamp is not None else None,
                    "status": status,
                    "players": player_names,
                    "trader_team": trader,
                    "tradee_team": tradee,
                }
            )

        logger.info(f"Extracted {len(transactions)} transactions")
        return transactions

    def _extract_player(self, player) -> dict | None:
        """Extract a single player's data into a plain dict."""
        try:
            name = _safe_str(getattr(player, "full_name", ""))
            if not name:
                # Try name.full pattern
                name_obj = getattr(player, "name", None)
                if name_obj and hasattr(name_obj, "full"):
                    name = _safe_str(name_obj.full)
                elif name_obj:
                    name = _safe_str(name_obj)
            if not name:
                return None

            # Get stats
            stats = []
            player_stats = getattr(player, "player_stats", None)
            if player_stats and hasattr(player_stats, "stats"):
                for stat in player_stats.stats:
                    stat_id = getattr(stat, "stat_id", None)
                    value = getattr(stat, "value", None)
                    if stat_id is not None:
                        stats.append(
                            {
                                "stat_id": _safe_int(stat_id),
                                "value": _safe_float(value),
                            }
                        )

            # Get selected position
            selected_position = ""
            sel_pos = getattr(player, "selected_position", None)
            if sel_pos:
                selected_position = _safe_str(
                    getattr(sel_pos, "position", "") or getattr(sel_pos, "selected_position", "")
                )

            # Get eligible positions
            eligible = getattr(player, "eligible_positions", None) or []
            if not isinstance(eligible, list):
                eligible = [eligible]
            eligible_positions = []
            for pos in eligible:
                if isinstance(pos, str):
                    eligible_positions.append(pos)
                elif hasattr(pos, "position"):
                    eligible_positions.append(_safe_str(pos.position))

            return {
                "yahoo_id": str(getattr(player, "player_id", "") or ""),
                "name": name,
                "team": _safe_str(getattr(player, "editorial_team_abbr", "")),
                "position": _safe_str(
                    getattr(player, "primary_position", "")
                    or getattr(player, "display_position", "")
                ),
                "selected_position": selected_position,
                "eligible_positions": eligible_positions,
                "status": _safe_str(getattr(player, "status", "")),
                "player_points": _safe_float(getattr(player, "player_points_value", 0)),
                "stats": stats,
            }
        except Exception as e:
            logger.warning(f"Failed to extract player: {e}")
            return None
