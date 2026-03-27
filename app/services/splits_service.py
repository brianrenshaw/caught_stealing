"""On-demand player splits fetch and DB cache.

Fetches platoon (vs LHP / vs RHP) and home/away splits from
pybaseball's Baseball Reference scraper. Data is cached in the
player_splits table and refreshed when stale (>24 hours).
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.player import Player
from app.models.player_splits import PlayerSplits

logger = logging.getLogger(__name__)

STALE_THRESHOLD = timedelta(hours=24)

# Mapping from pybaseball split names to our split_type values
SPLIT_MAP = {
    "vs LHP": "vs_lhp",
    "vs RHP": "vs_rhp",
    "Home": "home",
    "Away": "away",
}


async def get_splits(
    session: AsyncSession, player_id: int, season: int
) -> dict[str, dict[str, float | None]]:
    """Get splits from DB, fetching on-demand if missing or stale.

    Returns dict keyed by split_type: {"vs_lhp": {"pa": ..., "avg": ...}, ...}
    """
    result = await session.execute(
        select(PlayerSplits).where(
            PlayerSplits.player_id == player_id,
            PlayerSplits.season == season,
        )
    )
    existing = result.scalars().all()

    # Check freshness
    if existing and all(
        (datetime.now(timezone.utc) - s.updated_at) < STALE_THRESHOLD for s in existing
    ):
        return _splits_to_dict(existing)

    # Try to fetch fresh data
    player = await session.get(Player, player_id)
    if not player or not player.bbref_id:
        return _splits_to_dict(existing) if existing else {}

    fetched = await _fetch_and_store_splits(session, player, season)
    return _splits_to_dict(fetched) if fetched else _splits_to_dict(existing) if existing else {}


async def _fetch_and_store_splits(
    session: AsyncSession, player: Player, season: int
) -> list[PlayerSplits]:
    """Fetch splits from pybaseball and upsert to DB."""
    try:
        split_data = await asyncio.to_thread(_fetch_splits_sync, player.bbref_id, season)
    except Exception:
        logger.warning(f"Failed to fetch splits for {player.name} ({player.bbref_id})")
        return []

    if not split_data:
        return []

    # Determine player type
    player_type = "batter"  # default; could be refined if needed

    splits: list[PlayerSplits] = []
    for split_name, stats in split_data.items():
        split_type = SPLIT_MAP.get(split_name)
        if not split_type:
            continue

        # Check for existing record to update
        result = await session.execute(
            select(PlayerSplits).where(
                PlayerSplits.player_id == player.id,
                PlayerSplits.season == season,
                PlayerSplits.split_type == split_type,
                PlayerSplits.player_type == player_type,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            for attr, val in stats.items():
                if hasattr(existing, attr):
                    setattr(existing, attr, val)
            existing.updated_at = datetime.now(timezone.utc)
            splits.append(existing)
        else:
            new_split = PlayerSplits(
                player_id=player.id,
                season=season,
                split_type=split_type,
                player_type=player_type,
                pa=stats.get("pa"),
                avg=stats.get("avg"),
                obp=stats.get("obp"),
                slg=stats.get("slg"),
                ops=stats.get("ops"),
                woba=stats.get("woba"),
                k_pct=stats.get("k_pct"),
                bb_pct=stats.get("bb_pct"),
                hr=stats.get("hr"),
                iso=stats.get("iso"),
            )
            session.add(new_split)
            splits.append(new_split)

    await session.commit()
    return splits


def _fetch_splits_sync(bbref_id: str, season: int) -> dict[str, dict[str, float | None]]:
    """Synchronous pybaseball call to get splits data.

    Returns dict: {"vs LHP": {"pa": ..., "avg": ...}, "vs RHP": {...}, ...}
    """
    try:
        from pybaseball import get_splits
    except ImportError:
        logger.error("pybaseball not installed, cannot fetch splits")
        return {}

    try:
        result = get_splits(bbref_id, year=season)
        # get_splits returns a tuple: (switch_data_df, regular_df)
        # or just a DataFrame depending on version
        if isinstance(result, tuple):
            df = result[1] if len(result) > 1 else result[0]
        else:
            df = result

        if df is None or df.empty:
            return {}

        splits = {}
        for split_name in ["vs LHP", "vs RHP", "Home", "Away"]:
            row = df[df["Split"] == split_name] if "Split" in df.columns else None
            if row is not None and not row.empty:
                row = row.iloc[0]
                splits[split_name] = _parse_split_row(row)

        return splits
    except Exception as e:
        logger.warning(f"pybaseball get_splits failed for {bbref_id}: {e}")
        return {}


def _parse_split_row(row) -> dict[str, float | None]:
    """Parse a pybaseball splits row into our stat dict."""

    def safe_float(val, default=None):
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    pa = safe_float(row.get("PA"))
    bb = safe_float(row.get("BB"))
    so = safe_float(row.get("SO"))
    hr = safe_float(row.get("HR"))

    avg = safe_float(row.get("BA"))
    obp = safe_float(row.get("OBP"))
    slg = safe_float(row.get("SLG"))
    ops = safe_float(row.get("OPS"))

    # Compute derived stats if raw data available
    k_pct = None
    bb_pct = None
    iso = None
    if pa and pa > 0:
        if so is not None:
            k_pct = round(so / pa, 3)
        if bb is not None:
            bb_pct = round(bb / pa, 3)
    if slg is not None and avg is not None:
        iso = round(slg - avg, 3)

    return {
        "pa": pa,
        "avg": avg,
        "obp": obp,
        "slg": slg,
        "ops": ops,
        "woba": safe_float(row.get("wOBA")),
        "k_pct": k_pct,
        "bb_pct": bb_pct,
        "hr": hr,
        "iso": iso,
    }


def _splits_to_dict(
    splits: list[PlayerSplits],
) -> dict[str, dict[str, float | None]]:
    """Convert list of PlayerSplits models to nested dict."""
    result = {}
    for s in splits:
        result[s.split_type] = {
            "pa": s.pa,
            "avg": s.avg,
            "obp": s.obp,
            "slg": s.slg,
            "ops": s.ops,
            "woba": s.woba,
            "k_pct": s.k_pct,
            "bb_pct": s.bb_pct,
            "hr": s.hr,
            "iso": s.iso,
        }
    return result
