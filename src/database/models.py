"""竞彩足球 HAD 的 SQLAlchemy 数据模型。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.mysql import BaseModel


class Match(BaseModel):
    """一场官网比赛的稳定信息、状态和最终赛果。"""

    __tablename__ = "matches"
    __table_args__ = (
        CheckConstraint(
            "total_goals IS NULL OR total_goals = home_goals + away_goals",
            name="ck_matches_total_goals",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="比赛表自增主键"
    )
    official_match_id: Mapped[int] = mapped_column(
        Integer, unique=True, nullable=False, index=True, comment="中国官网比赛唯一标识 matchId"
    )
    match_number: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="竞彩编号，例如周五002"
    )
    business_date: Mapped[date] = mapped_column(
        Date, nullable=False, index=True, comment="竞彩彩票业务日期（中国时区）"
    )
    league_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="中国官网联赛唯一标识 leagueId"
    )
    league_name: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="联赛完整名称"
    )
    home_team: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="主队完整名称"
    )
    away_team: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="客队完整名称"
    )
    kickoff_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="计划开赛时间（中国时区）"
    )
    match_status: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="官网比赛状态"
    )
    sale_status: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="官网竞彩销售状态代码"
    )
    home_goals: Mapped[int | None] = mapped_column(
        Integer, comment="主队常规时间及伤停补时进球数，未完场为空"
    )
    away_goals: Mapped[int | None] = mapped_column(
        Integer, comment="客队常规时间及伤停补时进球数，未完场为空"
    )
    total_goals: Mapped[int | None] = mapped_column(
        Integer, comment="全场总进球数，等于主队进球数加客队进球数"
    )
    had_result: Mapped[str | None] = mapped_column(
        String(1), comment="胜平负赛果：H 主胜、D 平局、A 客胜，未开奖为空"
    )
    had_payout: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3), comment="HAD 开奖固定奖金，未开奖为空"
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="程序首次发现该比赛的中国本地时间"
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="程序最近一次在当前赛程发现该比赛的时间"
    )
    result_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="最近一次回填或修正赛果的中国本地时间"
    )

    odds_snapshots: Mapped[list["OddsSnapshot"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )


class OddsSnapshot(BaseModel):
    """官网某一发布时间对应的 HAD 三项固定赔率。"""

    __tablename__ = "odds_snapshots"
    __table_args__ = (
        # 这是同步幂等性的数据库兜底；仓储仍会预查以识别“同时间不同赔率”冲突。
        UniqueConstraint("match_id", "official_updated_at", name="uq_odds_match_updated"),
        Index("ix_odds_match_updated", "match_id", "official_updated_at"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="赔率快照表自增主键"
    )
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id"), nullable=False, comment="关联 matches.id 的比赛主键"
    )
    home_odds: Mapped[Decimal] = mapped_column(
        Numeric(10, 3), nullable=False, comment="HAD 主胜固定赔率"
    )
    draw_odds: Mapped[Decimal] = mapped_column(
        Numeric(10, 3), nullable=False, comment="HAD 平局固定赔率"
    )
    away_odds: Mapped[Decimal] = mapped_column(
        Numeric(10, 3), nullable=False, comment="HAD 客胜固定赔率"
    )
    official_updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="官网发布该组赔率的中国本地时间"
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="程序实际抓取该组赔率的中国本地时间"
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="赔率数据来源标识，当前为 sporttery"
    )

    match: Mapped[Match] = relationship(back_populates="odds_snapshots")
