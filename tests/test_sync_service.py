import copy
from contextlib import contextmanager
from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.crawler.match_crawler import UpstreamError
from src.database.models import BaseModel, Match, OddsSnapshot
from src.services.sync_service import BackfillService, SyncService


def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    BaseModel.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


class FakeClient:
    def __init__(self, schedule, detail, results, failing_ids=()):
        self.schedule = schedule
        self.detail = detail
        self.results = results
        self.failing_ids = set(failing_ids)

    def fetch_schedule(self):
        return copy.deepcopy(self.schedule)

    def fetch_detail(self, match_id):
        if match_id in self.failing_ids:
            raise UpstreamError("模拟单场失败")
        payload = copy.deepcopy(self.detail)
        payload["value"]["oddsHistory"]["matchId"] = match_id
        return payload

    def fetch_results(self, begin, end):
        return copy.deepcopy(self.results)


def test_repeated_sync_is_idempotent_and_fills_result(load_fixture):
    sessions = factory()
    client = FakeClient(load_fixture("schedule.json"), load_fixture("detail.json"), load_fixture("results.json"))
    first = SyncService(client, sessions).run()
    second = SyncService(client, sessions).run()
    assert (first.matches_created, first.odds_inserted, first.results_filled) == (1, 2, 1)
    assert (second.matches_created, second.odds_inserted, second.results_filled) == (0, 0, 0)
    with sessions() as session:
        assert len(session.scalars(select(Match)).all()) == 1
        assert len(session.scalars(select(OddsSnapshot)).all()) == 2


def test_one_match_failure_does_not_block_other_match(load_fixture):
    schedule = load_fixture("schedule.json")
    second = copy.deepcopy(schedule["value"]["matchInfoList"][0]["subMatchList"][0])
    second.update(matchId=8, matchNumStr="周五003", homeTeamAllName="另一主队")
    schedule["value"]["matchInfoList"][0]["subMatchList"].append(second)
    results = load_fixture("results.json")
    client = FakeClient(schedule, load_fixture("detail.json"), results, failing_ids={8})
    summary = SyncService(client, factory()).run()
    assert summary.matches_created == 2
    assert summary.odds_inserted == 2
    assert summary.failures == [{"match_id": 8, "error": "官网请求失败: 模拟单场失败"}]


def test_backfill_discovers_historical_match_and_writes_result(load_fixture):
    sessions = factory()

    class HistoricalClient:
        def fetch_results(self, begin, end):
            assert begin == end
            return load_fixture("historical_results.json")

    summary = BackfillService(HistoricalClient(), sessions).run(
        date(2026, 1, 1), date(2026, 1, 1)
    )
    assert (summary.days_processed, summary.matches_created, summary.results_filled) == (1, 1, 1)
    with sessions() as session:
        match = session.scalar(select(Match).where(Match.official_match_id == 2036530))
        assert match.kickoff_at is None
        assert (match.home_goals, match.away_goals, match.had_result) == (1, 0, "H")


def test_backfill_inserts_matches_in_official_id_order(load_fixture):
    sessions = factory()
    payload = load_fixture("historical_results.json")
    earlier = copy.deepcopy(payload["value"]["matchResult"][0])
    earlier.update(matchId=2036529, matchNumStr="周四020")
    payload["value"]["matchResult"].insert(0, payload["value"]["matchResult"].pop())
    payload["value"]["matchResult"].append(earlier)

    class HistoricalClient:
        def fetch_results(self, begin, end):
            return payload

    BackfillService(HistoricalClient(), sessions).run(date(2026, 1, 1), date(2026, 1, 1))
    with sessions() as session:
        ids = session.scalars(select(Match.official_match_id).order_by(Match.id)).all()
    assert ids == [2036529, 2036530]
