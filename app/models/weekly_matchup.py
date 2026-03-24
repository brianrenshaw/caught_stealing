"""Weekly matchup snapshot — stores projected (frozen) and actual (live) H2H points."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.player import Base


class WeeklyMatchupSnapshot(Base):
    __tablename__ = "weekly_matchup_snapshots"
    __table_args__ = (
        UniqueConstraint("season", "week", name="uq_matchup_season_week"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    my_team_id: Mapped[str] = mapped_column(String, nullable=False)
    my_team_name: Mapped[str] = mapped_column(String, nullable=False)
    opponent_team_id: Mapped[str] = mapped_column(String, nullable=False)
    opponent_team_name: Mapped[str] = mapped_column(String, nullable=False)

    # Frozen projections (set once when snapshot created)
    my_projected_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    opponent_projected_points: Mapped[float | None] = mapped_column(Float, nullable=True)

    # App's custom projection totals (frozen at creation alongside Yahoo's)
    my_app_projected_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    opponent_app_projected_points: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Live actuals (updated each sync)
    my_actual_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    opponent_actual_points: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Per-player weekly data as JSON (category breakdown)
    my_player_stats: Mapped[str | None] = mapped_column(Text, nullable=True)
    opponent_player_stats: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Projected category breakdown (frozen)
    my_projected_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    opponent_projected_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Actual category breakdown (live)
    my_actual_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    opponent_actual_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
