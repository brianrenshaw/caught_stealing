"""PlayerPoints model — stores computed fantasy points for the league scoring system.

This table is the foundation for ALL rankings and recommendations.
Every other module queries this table rather than recalculating.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.player import Base


class PlayerPoints(Base):
    __tablename__ = "player_points"
    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "season",
            "period",
            name="uq_player_points_player_season_period",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("players.id"), nullable=False, index=True
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    period: Mapped[str] = mapped_column(
        String, nullable=False
    )  # full_season, last_30, last_14, last_7
    player_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # hitter, pitcher

    # Points totals
    actual_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    projected_ros_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    steamer_ros_points: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Rate stats (nullable — only populated for relevant player types)
    points_per_pa: Mapped[float | None] = mapped_column(Float, nullable=True)  # hitters
    points_per_ip: Mapped[float | None] = mapped_column(Float, nullable=True)  # pitchers
    points_per_start: Mapped[float | None] = mapped_column(Float, nullable=True)  # starters
    points_per_appearance: Mapped[float | None] = mapped_column(Float, nullable=True)  # relievers

    # Rankings
    positional_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    surplus_value: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # points above replacement

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    player: Mapped["Player"] = relationship(back_populates="player_points")  # noqa: F821
