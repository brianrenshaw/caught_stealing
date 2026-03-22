from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.player import Base


class StatcastSummary(Base):
    __tablename__ = "statcast_summary"
    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "season",
            "period",
            "player_type",
            name="uq_statcast_player_season_period_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id"), nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    period: Mapped[str] = mapped_column(String, nullable=False)  # full_season, last_30, last_14
    player_type: Mapped[str] = mapped_column(String, nullable=False)  # batter, pitcher

    pa: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_exit_velo: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_exit_velo: Mapped[float | None] = mapped_column(Float, nullable=True)
    barrel_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    hard_hit_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    xba: Mapped[float | None] = mapped_column(Float, nullable=True)
    xslg: Mapped[float | None] = mapped_column(Float, nullable=True)
    xwoba: Mapped[float | None] = mapped_column(Float, nullable=True)
    sweet_spot_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sprint_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    whiff_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    chase_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    player: Mapped["Player"] = relationship(back_populates="statcast_summaries")  # noqa: F821
