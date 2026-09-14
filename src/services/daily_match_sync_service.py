"""当天竞彩业务日赛程与 HAD 赔率采集服务。"""

import time
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.database.models import Match, SyncRecord
from src.database.repository import MatchRepository, OddsWrite
from src.parsers import parse_detail, parse_leagues, parse_schedule
from src.services.sync_service import SyncService, SyncSummary


class DailyMatchSyncService:
    """只同步当天赛程和赔率，明确不查询或回填当天赛果。"""

    def __init__(self, client, session_factory, request_interval_seconds=1.0,
                 sleeper=time.sleep, record_sync=True):
        self.client, self.session_factory = client, session_factory
        self.request_interval_seconds, self.sleeper = request_interval_seconds, sleeper
        self.record_sync = record_sync

    def run(self, target_business_date: date | None = None, trigger_source: str = "internal") -> SyncSummary:
        target = target_business_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
        batch_id = str(uuid4())
        schedule_record_id = self._start_record(batch_id, "schedule", trigger_source, target) if self.record_sync else None
        try:
            payload = self.client.fetch_schedule()
        except Exception as exc:
            if self.record_sync:
                self._finish_record(schedule_record_id, "failed", 0, 0, 0, 1, str(exc))
            raise
        matches = sorted(
            (item for item in parse_schedule(payload) if item.business_date == target),
            key=lambda item: item.official_match_id,
        )
        summary = SyncSummary()
        if not matches:
            if self.record_sync:
                self._finish_record(schedule_record_id, "success", 0, 0, 0, 0)
                odds_id = self._start_record(batch_id, "odds", trigger_source, target)
                self._finish_record(odds_id, "success", 0, 0, 0, 0)
            return summary
        schedule_failures = []
        ready = []
        try:
            with self.session_factory() as session, session.begin():
                repo = MatchRepository(session)
                for league in parse_leagues(payload):
                    summary.leagues_created += repo.add_league(league)
        except Exception as exc:
            schedule_failures.append(f"联赛写入失败: {exc}")
        for data in matches:
            try:
                with self.session_factory() as session, session.begin():
                    _, state = MatchRepository(session).upsert_match(data)
                summary.matches_created += state == "created"
                summary.matches_updated += state == "updated"
                ready.append(data)
            except Exception as exc:
                message = f"比赛 {data.official_match_id} 写入失败: {exc}"
                schedule_failures.append(message)
                SyncService._record_failure(summary, data.official_match_id, "当天赛程写入失败", exc)
        if self.record_sync:
            failed = len(schedule_failures)
            self._finish_record(
                schedule_record_id, "partial_failed" if failed else "success",
                len(matches), summary.matches_created, summary.matches_updated, failed,
                "; ".join(schedule_failures)[:2000] or None,
            )
            odds_id = self._start_record(batch_id, "odds", trigger_source, target)

        odds_failures_before = len(summary.failures)
        for index, data in enumerate(ready):
            try:
                snapshots, _ = parse_detail(self.client.fetch_detail(data.official_match_id), data.official_match_id)
                with self.session_factory() as session, session.begin():
                    match = session.scalar(select(Match).where(Match.official_match_id == data.official_match_id))
                    repo = MatchRepository(session)
                    for snapshot in snapshots:
                        outcome = repo.add_odds(match, snapshot)
                        summary.odds_inserted += outcome == OddsWrite.INSERTED
                        summary.odds_conflicts += outcome == OddsWrite.CONFLICT
            except Exception as exc:
                SyncService._record_failure(summary, data.official_match_id, "当天赔率同步失败", exc)
            summary.matches_processed += 1
            if index + 1 < len(ready) and self.request_interval_seconds > 0:
                self.sleeper(self.request_interval_seconds)
        if self.record_sync:
            failed = len(summary.failures) - odds_failures_before
            self._finish_record(
                odds_id, "partial_failed" if failed else "success",
                summary.matches_processed, summary.odds_inserted, 0, failed,
                "; ".join(item["error"] for item in summary.failures)[:2000] or None,
            )
        return summary

    def _start_record(self, batch_id, sync_type, source, target) -> int:
        """用独立短事务保存阶段开始，业务事务失败也不会抹去审计记录。"""
        with self.session_factory() as session, session.begin():
            record = MatchRepository(session).start_sync_record(batch_id, sync_type, source, target)
            return record.id

    def _finish_record(self, record_id, status, processed, created, updated, failed, error=None):
        """用独立短事务结束指定阶段记录。"""
        with self.session_factory() as session, session.begin():
            record = session.get(SyncRecord, record_id)
            MatchRepository(session).finish_sync_record(
                record, status, processed=processed, created=created,
                updated=updated, failed=failed, error_summary=error,
            )
