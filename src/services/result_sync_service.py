"""昨日及历史积压比赛的赛果、最终赔率和奖金回填服务。"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.database.models import Match
from src.database.repository import MatchRepository, OddsWrite
from src.parsers import parse_detail, parse_invalid_match_ids, parse_results
from src.services.sync_service import SyncService, SyncSummary


class ResultSyncService:
    """只处理截止日前仍缺赛果或奖金的有效比赛。"""

    def __init__(self, client, session_factory, target_loader=None):
        self.client, self.session_factory, self.target_loader = client, session_factory, target_loader

    def _load(self, cutoff):
        if self.target_loader:
            return self.target_loader(cutoff)
        with self.session_factory() as session:
            return [(m.official_match_id, m.match_date, m.home_goals is None or m.away_goals is None or m.had_result is None)
                    for m in MatchRepository(session).pending_results(cutoff)]

    def run(self, cutoff_business_date: date | None = None) -> SyncSummary:
        cutoff = cutoff_business_date or datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
        targets = self._load(cutoff)
        summary = SyncSummary()
        if not targets:
            return summary
        by_date = defaultdict(list)
        for match_id, match_date, needs_result in targets:
            if needs_result:
                by_date[match_date].append(match_id)
        results = {}
        invalid_ids = set()
        for match_date in sorted(by_date):
            try:
                payload = self.client.fetch_results(match_date, match_date)
                results.update(parse_results(payload))
                invalid_ids.update(parse_invalid_match_ids(payload))
            except Exception as exc:
                for match_id in by_date[match_date]:
                    SyncService._record_failure(summary, match_id, "赛果查询失败", exc)
        for match_id, _, needs_result in targets:
            try:
                if match_id in invalid_ids:
                    with self.session_factory() as session, session.begin():
                        match = session.scalar(select(Match).where(Match.official_match_id == match_id))
                        if MatchRepository(session).mark_invalid(match):
                            summary.matches_updated += 1
                    summary.matches_processed += 1
                    continue
                result = results.get(match_id)
                if needs_result and result is None:
                    continue
                snapshots, payout = parse_detail(self.client.fetch_detail(match_id), match_id)
                with self.session_factory() as session, session.begin():
                    match = session.scalar(select(Match).where(Match.official_match_id == match_id))
                    repo = MatchRepository(session)
                    if result is not None and repo.apply_result(match, result, payout):
                        summary.results_filled += 1
                    for snapshot in snapshots:
                        outcome = repo.add_odds(match, snapshot)
                        summary.odds_inserted += outcome == OddsWrite.INSERTED
                        summary.odds_conflicts += outcome == OddsWrite.CONFLICT
                    repo.apply_payout(match, payout)
            except Exception as exc:
                SyncService._record_failure(summary, match_id, "赛果回填失败", exc)
            summary.matches_processed += 1
        return summary
