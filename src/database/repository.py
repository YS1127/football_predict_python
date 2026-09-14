"""比赛和赔率的幂等持久化操作。"""

from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.database.models import League, Match, OddsSnapshot, SyncRecord
from src.domain import LeagueData, MatchData, MatchResultData, OddsSnapshotData


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

    def add_league(self, data: LeagueData) -> bool:
        """首次写入官网联赛；已存在时保持原简称和全称不变。"""
        existing = self.session.scalar(select(League).where(
            League.official_league_id == data.official_league_id
        ))
        if existing is not None:
            return False
        self.session.add(League(
            official_league_id=data.official_league_id,
            abbreviation=data.abbreviation,
            full_name=data.full_name,
        ))
        self.session.flush()
        return True

    def start_sync_record(self, batch_id: str, sync_type: str, trigger_source: str, target_date: date) -> SyncRecord:
        """创建 running 状态记录；调用方事务提交后可观察到任务已启动。"""
        record = SyncRecord(
            batch_id=batch_id, sync_type=sync_type, trigger_source=trigger_source,
            target_date=target_date, status="running", started_at=china_now_naive(),
            processed_count=0, created_count=0, updated_count=0, failed_count=0,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def finish_sync_record(self, record: SyncRecord, status: str, *, processed: int,
                           created: int, updated: int, failed: int,
                           error_summary: str | None = None) -> None:
        """以统计数据结束同步记录，不在错误摘要中保存敏感响应。"""
        record.status = status
        record.finished_at = china_now_naive()
        record.processed_count = processed
        record.created_count = created
        record.updated_count = updated
        record.failed_count = failed
        record.error_summary = error_summary
        self.session.flush()

    def upsert_match(self, data: MatchData) -> tuple[Match, str]:
        """按官网比赛 ID 新增或更新，并返回 created/updated/unchanged。"""
        entity = self.session.scalar(
            select(Match).where(Match.official_match_id == data.official_match_id)
        )
        now = china_now_naive()
        fields = {
            "match_number": data.match_number,
            "business_date": data.business_date,
            "match_date": data.match_date,
            "league_id": data.league_id,
            "league_name": data.league_name,
            "home_team": data.home_team,
            "away_team": data.away_team,
            "kickoff_at": data.kickoff_at,
            "match_status": data.match_status,
            "sale_status": data.sale_status,
            "is_valid": data.is_valid,
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
        if not data.is_valid:
            # 无效比赛仍保留身份与联赛信息用于核对，但业务结果必须整体清空，
            # 防止此前误解析的比分或奖金继续被下游当成有效赛果使用。
            entity.home_goals = None
            entity.away_goals = None
            entity.total_goals = None
            entity.had_result = None
            entity.had_payout = None
            entity.result_updated_at = None
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
        """回填最终赛果和可选奖金；未提供奖金时保留数据库已有值。"""
        if match.official_match_id != result.official_match_id:
            raise ValueError("赛果与比赛 ID 不一致")
        if not match.is_valid:
            return False
        # 历史赛果批量接口不负责开奖奖金。None 表示“本次未知”而非“清空”，
        # 防止历史回填覆盖详情同步已写入的奖金。
        effective_payout = match.had_payout if payout is None else payout
        values = (result.home_goals, result.away_goals, result.total_goals, result.had_result, effective_payout)
        current = (match.home_goals, match.away_goals, match.total_goals, match.had_result, match.had_payout)
        if current == values:
            return False
        match.home_goals, match.away_goals, match.total_goals, match.had_result, match.had_payout = values
        match.result_updated_at = china_now_naive()
        self.session.flush()
        return True

    def apply_payout(self, match: Match, payout) -> bool:
        """仅补充 HAD 开奖固定奖金，不触碰已保存的比分和赛果。"""
        if not match.is_valid or payout is None or match.had_payout == payout:
            return False
        match.had_payout = payout
        match.result_updated_at = china_now_naive()
        self.session.flush()
        return True

    def pending_matches(self) -> list[Match]:
        """返回尚无完整比分或尚无 HAD 开奖奖金的比赛。"""
        return list(self.session.scalars(select(Match).where(or_(
            Match.home_goals.is_(None), Match.away_goals.is_(None), Match.had_payout.is_(None)
        ))))

    def pending_results(self, cutoff: date) -> list[Match]:
        """按官网 ID 返回截止业务日前仍缺赛果或奖金的有效比赛。"""
        return list(self.session.scalars(select(Match).where(
            Match.business_date <= cutoff,
            Match.is_valid.is_(True),
            or_(Match.home_goals.is_(None), Match.away_goals.is_(None),
                Match.had_result.is_(None), Match.had_payout.is_(None)),
        ).order_by(Match.official_match_id.asc())))

    def mark_invalid(self, match: Match) -> bool:
        """将比赛标记无效并清除所有可能被误用的赛果字段。"""
        changed = match.is_valid or any(value is not None for value in (
            match.home_goals, match.away_goals, match.total_goals,
            match.had_result, match.had_payout, match.result_updated_at,
        ))
        match.is_valid = False
        match.home_goals = match.away_goals = match.total_goals = None
        match.had_result = match.had_payout = match.result_updated_at = None
        self.session.flush()
        return changed
