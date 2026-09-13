import copy
from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.crawler.match_crawler import UpstreamError
from src.database.models import BaseModel, Match, OddsSnapshot
from src.services.sync_service import SyncService


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
