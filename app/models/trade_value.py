from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.player import Base


class TradeValue(Base):
    __tablename__ = "trade_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id"), nullable=False)
    surplus_value: Mapped[float] = mapped_column(Float, nullable=False)
    positional_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    z_score_total: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    player: Mapped["Player"] = relationship(back_populates="trade_values")  # noqa: F821
