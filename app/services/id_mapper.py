import logging
from io import StringIO

import httpx
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.player import Player

logger = logging.getLogger(__name__)

# Smart Fantasy Baseball Player ID Map
# The GitHub repo was removed; the CSV is now hosted directly on their site.
SFBB_ID_MAP_URL = "https://www.smartfantasybaseball.com/PLAYERIDMAPCSV"


def _safe_str(val: object) -> str | None:
    """Convert a value to string, returning None for NaN/empty."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    # Clean up float-style numeric strings like "120074.0" → "120074"
    try:
        if "." in s:
            as_float = float(s)
            if as_float == int(as_float):
                return str(int(as_float))
    except (ValueError, OverflowError):
        pass
    return s


class PlayerIDMapper:
    def __init__(self) -> None:
        self._map_df: pd.DataFrame | None = None

    async def load_map(self) -> pd.DataFrame:
        if self._map_df is not None:
            return self._map_df

        logger.info("Downloading Smart Fantasy Baseball player ID map...")
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(SFBB_ID_MAP_URL, timeout=30)
            resp.raise_for_status()

        self._map_df = pd.read_csv(StringIO(resp.text))
        logger.info(f"Loaded {len(self._map_df)} player ID mappings")
        return self._map_df

    async def yahoo_to_fangraphs(self, yahoo_id: str) -> str | None:
        df = await self.load_map()
        match = df[df["YAHOOID"].astype(str) == str(yahoo_id)]
        if not match.empty:
            return str(match.iloc[0]["IDFANGRAPHS"])
        return None

    async def fangraphs_to_mlbam(self, fangraphs_id: str) -> str | None:
        df = await self.load_map()
        match = df[df["IDFANGRAPHS"].astype(str) == str(fangraphs_id)]
        if not match.empty:
            return str(match.iloc[0]["MLBID"])
        return None

    async def yahoo_to_mlbam(self, yahoo_id: str) -> str | None:
        df = await self.load_map()
        match = df[df["YAHOOID"].astype(str) == str(yahoo_id)]
        if not match.empty:
            return str(match.iloc[0]["MLBID"])
        return None

    async def mlbam_to_yahoo(self, mlbam_id: str) -> str | None:
        df = await self.load_map()
        match = df[df["MLBID"].astype(str) == str(mlbam_id)]
        if not match.empty:
            return str(match.iloc[0]["YAHOOID"])
        return None

    async def lookup_player(self, name: str) -> pd.DataFrame:
        df = await self.load_map()
        mask = df["PLAYERNAME"].str.contains(name, case=False, na=False)
        return df[mask]

    def get_fangraphs_to_player_id_map(self, df: pd.DataFrame) -> dict[str, str]:
        """Build a FanGraphs ID → MLBAM ID lookup dict from the loaded SFBB map."""
        result: dict[str, str] = {}
        for row in df.itertuples(index=False):
            fg = _safe_str(getattr(row, "IDFANGRAPHS", None))
            mlb = _safe_str(getattr(row, "MLBID", None))
            if fg and mlb:
                result[fg] = mlb
        return result

    async def seed_crosswalk(self, session: AsyncSession) -> int:
        """Bulk-populate fangraphs_id, mlbam_id, bbref_id on existing Player records.

        Also creates Player records for active MLB players not yet in the DB
        (discovered via the SFBB map but not in the Yahoo league).

        Returns the number of players created or updated.
        """
        df = await self.load_map()
        count = 0

        # Build lookups of existing players by various IDs
        result = await session.execute(select(Player))
        all_players = list(result.scalars().all())
        existing_by_yahoo = {p.yahoo_id: p for p in all_players if p.yahoo_id}
        existing_by_mlbam = {p.mlbam_id: p for p in all_players if p.mlbam_id}
        existing_by_fangraphs = {p.fangraphs_id: p for p in all_players if p.fangraphs_id}
        existing_by_bbref = {p.bbref_id: p for p in all_players if p.bbref_id}

        # Track IDs we've already seen in this run to avoid duplicates from the CSV
        # (e.g. two-way players like Ohtani appear multiple times)
        seen_mlbam: set[str] = set()
        seen_bbref: set[str] = set()
        seen_fangraphs: set[str] = set()

        for row in df.itertuples(index=False):
            yahoo_id = _safe_str(getattr(row, "YAHOOID", None))
            fg_id = _safe_str(getattr(row, "IDFANGRAPHS", None))
            mlbam_id = _safe_str(getattr(row, "MLBID", None))
            bbref_id = _safe_str(getattr(row, "BREFID", None))
            name = _safe_str(getattr(row, "PLAYERNAME", None))
            team = _safe_str(getattr(row, "TEAM", None))
            pos = _safe_str(getattr(row, "POS", None))

            if not name:
                continue

            # Skip duplicate rows for the same player
            if mlbam_id and mlbam_id in seen_mlbam:
                continue

            # Find existing player by any known ID
            player = None
            if yahoo_id and yahoo_id in existing_by_yahoo:
                player = existing_by_yahoo[yahoo_id]
            elif mlbam_id and mlbam_id in existing_by_mlbam:
                player = existing_by_mlbam[mlbam_id]
            elif fg_id and fg_id in existing_by_fangraphs:
                player = existing_by_fangraphs[fg_id]
            elif bbref_id and bbref_id in existing_by_bbref:
                player = existing_by_bbref[bbref_id]

            if player:
                # Update cross-platform IDs if missing
                changed = False
                if fg_id and not player.fangraphs_id:
                    player.fangraphs_id = fg_id
                    changed = True
                if mlbam_id and not player.mlbam_id:
                    player.mlbam_id = mlbam_id
                    changed = True
                if bbref_id and not player.bbref_id:
                    player.bbref_id = bbref_id
                    changed = True
                if changed:
                    count += 1
            else:
                # Only create if we have at least an mlbam_id (active MLB player)
                # and none of the unique IDs are already taken
                if mlbam_id and (team and team != "FA"):
                    if (bbref_id and bbref_id in seen_bbref) or (fg_id and fg_id in seen_fangraphs):
                        continue
                    new_player = Player(
                        name=name,
                        team=team,
                        position=pos,
                        yahoo_id=yahoo_id,
                        fangraphs_id=fg_id,
                        mlbam_id=mlbam_id,
                        bbref_id=bbref_id,
                    )
                    session.add(new_player)
                    count += 1

            # Mark IDs as seen
            if mlbam_id:
                seen_mlbam.add(mlbam_id)
            if bbref_id:
                seen_bbref.add(bbref_id)
            if fg_id:
                seen_fangraphs.add(fg_id)

        await session.commit()
        logger.info(f"Seed crosswalk: created/updated {count} player records")
        return count

    async def ensure_player_exists(
        self,
        session: AsyncSession,
        *,
        fangraphs_id: str | None = None,
        mlbam_id: str | None = None,
        name: str = "",
        team: str | None = None,
        position: str | None = None,
    ) -> Player | None:
        """Find or create a Player record by fangraphs_id or mlbam_id."""
        if fangraphs_id:
            result = await session.execute(
                select(Player).where(Player.fangraphs_id == fangraphs_id)
            )
            player = result.scalar_one_or_none()
            if player:
                return player

        if mlbam_id:
            result = await session.execute(select(Player).where(Player.mlbam_id == mlbam_id))
            player = result.scalar_one_or_none()
            if player:
                # Backfill fangraphs_id if we have it now
                if fangraphs_id and not player.fangraphs_id:
                    player.fangraphs_id = fangraphs_id
                return player

        if not name:
            return None

        # Create new player
        player = Player(
            name=name,
            team=team,
            position=position,
            fangraphs_id=fangraphs_id,
            mlbam_id=mlbam_id,
        )
        session.add(player)
        await session.flush()
        return player


id_mapper = PlayerIDMapper()
