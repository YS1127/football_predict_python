"""同步流程各层之间传递的不可变领域数据。

这些对象不含 SQLAlchemy 状态，也不依赖 HTTP 响应结构，使解析、业务编排与数据库
持久化可以独立测试。所有 datetime 均表示中国本地时间，并按设计保持无 tzinfo。
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class LeagueData:
    """官网联赛字典的首次发现信息。"""

    official_league_id: int
    abbreviation: str
    full_name: str


@dataclass(frozen=True)
class MatchData:
    """从当前赛程解析得到的一场 HAD 比赛。"""
    official_match_id: int
    match_number: str
    business_date: date
    match_date: date
    league_id: int
    league_name: str
    home_team: str
    away_team: str
    kickoff_at: datetime | None
    match_status: str
    sale_status: int | None
    is_valid: bool


@dataclass(frozen=True)
class OddsSnapshotData:
    """官网在某个明确发布时间发布的一组三项 HAD 赔率。"""
    official_match_id: int
    home: Decimal
    draw: Decimal
    away: Decimal
    official_updated_at: datetime
    source: str = "sporttery"


@dataclass(frozen=True)
class MatchResultData:
    """按常规时间加伤停补时计算的最终比分与 HAD 结果。"""
    official_match_id: int
    home_goals: int
    away_goals: int
    total_goals: int
    had_result: str
