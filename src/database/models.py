"""竞彩足球 HAD 的 SQLAlchemy 数据模型。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.mysql import BaseModel


class League(BaseModel):
    """官网联赛字典；同一官网 ID 只保存首次发现的名称。"""

    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="联赛表自增主键"
    )
    official_league_id: Mapped[int] = mapped_column(
        Integer, unique=True, nullable=False, index=True, comment="中国官网联赛唯一标识 leagueId"
    )
    abbreviation: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="联赛简称"
    )
    full_name: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="联赛全称"
    )


class SyncRecord(BaseModel):
    """一次赛程或赔率同步阶段的执行记录。"""

    __tablename__ = "sync_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="同步记录自增主键")
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True, comment="同一次任务的批次 UUID")
    sync_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True, comment="同步类型：schedule赛程、odds赔率")
    trigger_source: Mapped[str] = mapped_column(String(16), nullable=False, comment="触发来源：scheduled、http、cli或internal")
    target_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="本次同步目标竞彩业务日期")
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True, comment="执行状态：running、success、partial_failed或failed")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="任务开始中国本地时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, comment="任务结束中国本地时间")
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="已处理比赛数量")
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="新增数据数量")
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="更新数据数量")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="失败比赛数量")
    error_summary: Mapped[str | None] = mapped_column(Text, comment="简短错误摘要，不保存完整官网响应")


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
    match_date: Mapped[date] = mapped_column(
        Date, nullable=False, index=True, comment="比赛自然日期，来源为官网 matchDate"
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
    kickoff_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="准确开赛时间；历史接口未提供时为空"
    )
    match_status: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="官网比赛状态"
    )
    sale_status: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="官网竞彩销售状态代码；历史接口不提供时为空"
    )
    is_valid: Mapped[bool] = mapped_column(
        nullable=False, default=True, comment="是否有效场次：1有效，0无效"
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
