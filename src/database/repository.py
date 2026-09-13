"""比赛和赔率的幂等持久化操作。"""

from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.database.models import Match, OddsSnapshot
from src.domain import MatchData, MatchResultData, OddsSnapshotData


CHINA_TZ = ZoneInfo("Asia/Shanghai")


def china_now_naive() -> datetime:
    """返回可直接写入 MySQL DATETIME 的中国本地时间（不附带 tzinfo）。"""
    return datetime.now(CHINA_TZ).replace(tzinfo=None)


class OddsWrite(str, Enum):
    """赔率写入结果，用于汇总新增、重复和冲突。"""

    INSERTED = "inserted"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"


class MatchRepository:
    """在调用方提供的 Session/事务中读写一场或多场比赛。"""

    def __init__(self, session: Session):
        self.session = session

    def upsert_match(self, data: MatchData) -> tuple[Match, str]:
        """按官网比赛 ID 新增或更新，并返回 created/updated/unchanged。"""
        entity = self.session.scalar(
            select(Match).where(Match.official_match_id == data.official_match_id)
        )
        now = china_now_naive()
        fields = {
            "match_number": data.match_number,
            "business_date": data.business_date,
            "league_id": data.league_id,
            "league_name": data.league_name,
            "home_team": data.home_team,
            "away_team": data.away_team,
            "kickoff_at": data.kickoff_at,
            "match_status": data.match_status,
            "sale_status": data.sale_status,
        }
        if entity is None:
            entity = Match(
                official_match_id=data.official_match_id,
                first_seen_at=now,
                last_seen_at=now,
                **fields,
            )
            self.session.add(entity)
            self.session.flush()
            return entity, "created"

        changed = any(getattr(entity, key) != value for key, value in fields.items())
        for key, value in fields.items():
            setattr(entity, key, value)
        entity.last_seen_at = now
        self.session.flush()
        return entity, "updated" if changed else "unchanged"

    def add_odds(self, match: Match, data: OddsSnapshotData) -> OddsWrite:
        """追加一个快照；相同时间赔率不同即报告冲突并保留数据库原值。"""
        existing = self.session.scalar(select(OddsSnapshot).where(
            OddsSnapshot.match_id == match.id,
            OddsSnapshot.official_updated_at == data.official_updated_at,
        ))
        if existing is not None:
            same = (
                existing.home_odds == data.home
                and existing.draw_odds == data.draw
                and existing.away_odds == data.away
            )
            return OddsWrite.DUPLICATE if same else OddsWrite.CONFLICT
        self.session.add(OddsSnapshot(
            match_id=match.id,
            home_odds=data.home,
            draw_odds=data.draw,
            away_odds=data.away,
            official_updated_at=data.official_updated_at,
            fetched_at=china_now_naive(),
            source=data.source,
        ))
        self.session.flush()
        return OddsWrite.INSERTED

    def apply_result(self, match: Match, result: MatchResultData, payout) -> bool:
        """回填最终赛果和 HAD 奖金；值没有变化时不重复计为回填。"""
        if match.official_match_id != result.official_match_id:
            raise ValueError("赛果与比赛 ID 不一致")
        values = (result.home_goals, result.away_goals, result.total_goals, result.had_result, payout)
        current = (match.home_goals, match.away_goals, match.total_goals, match.had_result, match.had_payout)
        if current == values:
            return False
        match.home_goals, match.away_goals, match.total_goals, match.had_result, match.had_payout = values
        match.result_updated_at = china_now_naive()
        self.session.flush()
        return True

    def pending_matches(self) -> list[Match]:
        """返回尚无完整比分或尚无 HAD 开奖奖金的比赛。"""
        return list(self.session.scalars(select(Match).where(or_(
            Match.home_goals.is_(None), Match.away_goals.is_(None), Match.had_payout.is_(None)
        ))))
