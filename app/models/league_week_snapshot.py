"""League-wide weekly snapshot — stores standings + scoreboard data for all teams each week."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.player import Base


class LeagueWeekSnapshot(Base):
    __tablename__ = "league_week_snapshots"
    __table_args__ = (UniqueConstraint("season", "week", "team_id", name="uq_league_week_team"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    team_id: Mapped[str] = mapped_column(String, nullable=False)
    team_name: Mapped[str] = mapped_column(String, nullable=False)
    is_my_team: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Standings at time of snapshot
    rank: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ties: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    points_for: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    points_against: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Weekly matchup data (from Yahoo scoreboard)
    opponent_team_id: Mapped[str | None] = mapped_column(String, nullable=True)
    opponent_team_name: Mapped[str | None] = mapped_column(String, nullable=True)
    yahoo_projected_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    opponent_actual_points: Mapped[float | None] = mapped_column(Float, nullable=True)

    # App projection (only populated for is_my_team=True)
    app_projected_points: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
