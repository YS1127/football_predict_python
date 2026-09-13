"""当天竞彩业务日赛程与 HAD 赔率采集服务。"""

import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.database.models import Match
from src.database.repository import MatchRepository, OddsWrite
from src.parsers import parse_detail, parse_leagues, parse_schedule
from src.services.sync_service import SyncService, SyncSummary


class DailyMatchSyncService:
    """只同步当天赛程和赔率，明确不查询或回填当天赛果。"""

    def __init__(self, client, session_factory, request_interval_seconds=1.0, sleeper=time.sleep):
        self.client, self.session_factory = client, session_factory
        self.request_interval_seconds, self.sleeper = request_interval_seconds, sleeper

    def run(self, target_business_date: date | None = None) -> SyncSummary:
        target = target_business_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
        payload = self.client.fetch_schedule()
        matches = sorted(
            (item for item in parse_schedule(payload) if item.business_date == target),
            key=lambda item: item.official_match_id,
        )
        summary = SyncSummary()
        if not matches:
            return summary
        with self.session_factory() as session, session.begin():
            repo = MatchRepository(session)
            for league in parse_leagues(payload):
                summary.leagues_created += repo.add_league(league)
        for index, data in enumerate(matches):
            try:
                with self.session_factory() as session, session.begin():
                    match, state = MatchRepository(session).upsert_match(data)
                summary.matches_created += state == "created"
                summary.matches_updated += state == "updated"
                snapshots, _ = parse_detail(self.client.fetch_detail(data.official_match_id), data.official_match_id)
                with self.session_factory() as session, session.begin():
                    match = session.scalar(select(Match).where(Match.official_match_id == data.official_match_id))
                    repo = MatchRepository(session)
                    for snapshot in snapshots:
                        outcome = repo.add_odds(match, snapshot)
                        summary.odds_inserted += outcome == OddsWrite.INSERTED
                        summary.odds_conflicts += outcome == OddsWrite.CONFLICT
            except Exception as exc:
                SyncService._record_failure(summary, data.official_match_id, "当天比赛同步失败", exc)
            summary.matches_processed += 1
            if index + 1 < len(matches) and self.request_interval_seconds > 0:
                self.sleeper(self.request_interval_seconds)
        return summary
