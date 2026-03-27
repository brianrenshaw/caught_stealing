"""Normalize extracted data into shapes matching SQLAlchemy models."""

import logging
from datetime import datetime

from app.config import settings

logger = logging.getLogger(__name__)


class DataTransformer:
    """Transforms raw extracted data into dicts ready for database loading."""

    def __init__(self, stat_categories: dict[int, dict] | None = None) -> None:
        self.stat_categories = stat_categories or {}

    def transform_players(self, roster_data: dict[str, dict]) -> list[dict]:
        """Flatten all players across all teams into Player model dicts.

        Deduplicates by yahoo_id (a player might appear in transactions too).
        """
        seen_ids = set()
        players = []

        for team_data in roster_data.values():
            for player in team_data.get("players", []):
                yahoo_id = player.get("yahoo_id", "")
                if not yahoo_id or yahoo_id in seen_ids:
                    continue
                seen_ids.add(yahoo_id)

                players.append(
                    {
                        "name": player.get("name", "Unknown"),
                        "team": player.get("team", ""),
                        "position": player.get("position", ""),
                        "yahoo_id": yahoo_id,
                    }
                )

        logger.info(f"Transformed {len(players)} unique players")
        return players

    def transform_rosters(
        self,
        roster_data: dict[str, dict],
        player_db_map: dict[str, int],
    ) -> list[dict]:
        """Transform roster data into Roster model dicts.

        Args:
            roster_data: Raw roster data keyed by team_id.
            player_db_map: Mapping of yahoo_id -> database player.id.
        """
        rosters = []

        for team_data in roster_data.values():
            team_id = team_data.get("team_id", "")
            team_name = team_data.get("team_name", "Unknown")
            is_my_team = team_data.get("is_my_team", False)

            for player in team_data.get("players", []):
                yahoo_id = player.get("yahoo_id", "")
                db_player_id = player_db_map.get(yahoo_id)
                if not db_player_id:
                    continue

                rosters.append(
                    {
                        "league_id": settings.yahoo_league_id,
                        "team_id": team_id,
                        "team_name": team_name,
                        "player_id": db_player_id,
                        "roster_position": player.get("selected_position", "BN"),
                        "is_my_team": is_my_team,
                    }
                )

        logger.info(f"Transformed {len(rosters)} roster entries")
        return rosters

    def transform_stats(
        self,
        roster_data: dict[str, dict],
        player_db_map: dict[str, int],
    ) -> list[dict]:
        """Transform player stats into Stat model dicts.

        Uses stat_categories to map stat_id -> human-readable stat name.
        """
        stats = []
        season = datetime.now(timezone.utc).year

        for team_data in roster_data.values():
            for player in team_data.get("players", []):
                yahoo_id = player.get("yahoo_id", "")
                db_player_id = player_db_map.get(yahoo_id)
                if not db_player_id:
                    continue

                position = player.get("position", "")
                stat_type = self._infer_stat_type(position)

                for stat in player.get("stats", []):
                    stat_id = stat.get("stat_id")
                    value = stat.get("value", 0.0)

                    cat = self.stat_categories.get(stat_id, {})
                    stat_name = cat.get("abbr") or cat.get("display_name") or str(stat_id)

                    stats.append(
                        {
                            "player_id": db_player_id,
                            "season": season,
                            "stat_type": stat_type,
                            "stat_name": stat_name,
                            "value": value,
                            "source": "yahoo",
                        }
                    )

        logger.info(f"Transformed {len(stats)} stat entries")
        return stats

    def _infer_stat_type(self, position: str) -> str:
        """Infer batting vs pitching from position string."""
        pitching_positions = {"SP", "RP", "P"}
        positions = {p.strip() for p in position.split(",")}
        if positions & pitching_positions:
            return "pitching"
        return "batting"
