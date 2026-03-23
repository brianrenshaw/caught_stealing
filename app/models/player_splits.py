from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.player import Base


class PlayerSplits(Base):
    __tablename__ = "player_splits"
    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "season",
            "split_type",
            "player_type",
            name="uq_splits_player_season_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("players.id"), nullable=False, index=True
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    split_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # vs_lhp, vs_rhp, home, away
    player_type: Mapped[str] = mapped_column(String, nullable=False)  # batter, pitcher

    # Stats
    pa: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    obp: Mapped[float | None] = mapped_column(Float, nullable=True)
    slg: Mapped[float | None] = mapped_column(Float, nullable=True)
    ops: Mapped[float | None] = mapped_column(Float, nullable=True)
    woba: Mapped[float | None] = mapped_column(Float, nullable=True)
    k_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    iso: Mapped[float | None] = mapped_column(Float, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    player: Mapped["Player"] = relationship(back_populates="splits")  # noqa: F821
