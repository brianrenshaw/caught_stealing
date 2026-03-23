from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    team: Mapped[str | None] = mapped_column(String, nullable=True)
    position: Mapped[str | None] = mapped_column(String, nullable=True)
    yahoo_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    fangraphs_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    mlbam_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    bbref_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    stats: Mapped[list["Stat"]] = relationship(back_populates="player")  # noqa: F821
    projections: Mapped[list["Projection"]] = relationship(back_populates="player")  # noqa: F821
    rosters: Mapped[list["Roster"]] = relationship(back_populates="player")  # noqa: F821
    trade_values: Mapped[list["TradeValue"]] = relationship(back_populates="player")  # noqa: F821
    batting_stats: Mapped[list["BattingStats"]] = relationship(back_populates="player")  # noqa: F821
    pitching_stats: Mapped[list["PitchingStats"]] = relationship(back_populates="player")  # noqa: F821
    statcast_summaries: Mapped[list["StatcastSummary"]] = relationship(back_populates="player")  # noqa: F821
    splits: Mapped[list["PlayerSplits"]] = relationship(back_populates="player")  # noqa: F821
    player_points: Mapped[list["PlayerPoints"]] = relationship(back_populates="player")  # noqa: F821
