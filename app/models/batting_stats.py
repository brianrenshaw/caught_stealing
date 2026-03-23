from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.player import Base


class BattingStats(Base):
    __tablename__ = "batting_stats"
    __table_args__ = (
        UniqueConstraint(
            "player_id", "season", "period", "source", name="uq_batting_player_season_period_source"
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

    # Counting stats
    pa: Mapped[float | None] = mapped_column(Float, nullable=True)
    ab: Mapped[float | None] = mapped_column(Float, nullable=True)
    h: Mapped[float | None] = mapped_column(Float, nullable=True)
    doubles: Mapped[float | None] = mapped_column(Float, nullable=True)
    triples: Mapped[float | None] = mapped_column(Float, nullable=True)
    hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    r: Mapped[float | None] = mapped_column(Float, nullable=True)
    rbi: Mapped[float | None] = mapped_column(Float, nullable=True)
    sb: Mapped[float | None] = mapped_column(Float, nullable=True)
    cs: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb: Mapped[float | None] = mapped_column(Float, nullable=True)
    so: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Rate stats
    avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    obp: Mapped[float | None] = mapped_column(Float, nullable=True)
    slg: Mapped[float | None] = mapped_column(Float, nullable=True)
    ops: Mapped[float | None] = mapped_column(Float, nullable=True)
    woba: Mapped[float | None] = mapped_column(Float, nullable=True)
    wrc_plus: Mapped[float | None] = mapped_column(Float, nullable=True)
    iso: Mapped[float | None] = mapped_column(Float, nullable=True)
    babip: Mapped[float | None] = mapped_column(Float, nullable=True)
    k_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    war: Mapped[float | None] = mapped_column(Float, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    player: Mapped["Player"] = relationship(back_populates="batting_stats")  # noqa: F821
