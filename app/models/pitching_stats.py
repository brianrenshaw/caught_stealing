from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.player import Base


class PitchingStats(Base):
    __tablename__ = "pitching_stats"
    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "season",
            "period",
            "source",
            name="uq_pitching_player_season_period_source",
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
    source: Mapped[str] = mapped_column(String, nullable=False)  # fangraphs, yahoo

    # Record
    w: Mapped[float | None] = mapped_column(Float, nullable=True)
    l: Mapped[float | None] = mapped_column(Float, nullable=True)  # noqa: E741
    sv: Mapped[float | None] = mapped_column(Float, nullable=True)
    hld: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Workload
    g: Mapped[float | None] = mapped_column(Float, nullable=True)
    gs: Mapped[float | None] = mapped_column(Float, nullable=True)
    ip: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Counting
    h: Mapped[float | None] = mapped_column(Float, nullable=True)
    er: Mapped[float | None] = mapped_column(Float, nullable=True)
    hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb: Mapped[float | None] = mapped_column(Float, nullable=True)
    so: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Rate stats
    era: Mapped[float | None] = mapped_column(Float, nullable=True)
    whip: Mapped[float | None] = mapped_column(Float, nullable=True)
    k_per_9: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb_per_9: Mapped[float | None] = mapped_column(Float, nullable=True)
    fip: Mapped[float | None] = mapped_column(Float, nullable=True)
    xfip: Mapped[float | None] = mapped_column(Float, nullable=True)
    siera: Mapped[float | None] = mapped_column(Float, nullable=True)
    k_bb_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    war: Mapped[float | None] = mapped_column(Float, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    player: Mapped["Player"] = relationship(back_populates="pitching_stats")  # noqa: F821
