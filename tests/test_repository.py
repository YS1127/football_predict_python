from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.database.models import BaseModel, Match, OddsSnapshot
from src.database.repository import MatchRepository, OddsWrite
from src.domain import MatchData, MatchResultData, OddsSnapshotData


def make_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    BaseModel.metadata.create_all(engine)
    return Session(engine)


def test_every_database_column_has_a_comment():
    """防止新增字段时遗漏源码及 MySQL 中可见的字段说明。"""
    uncommented = [
        f"{table.name}.{column.name}"
        for table in BaseModel.metadata.sorted_tables
        for column in table.columns
        if not column.comment
    ]
    assert uncommented == []


def match_data():
    return MatchData(7, "周一001", date(2026, 9, 13), 101, "测试联赛", "主队", "客队",
                     datetime(2026, 9, 13, 20), "Selling", 2)


def odds(home="2.10"):
    return OddsSnapshotData(7, Decimal(home), Decimal("3.20"), Decimal("3.00"),
                            datetime(2026, 9, 13, 12))


def test_upsert_match_reports_created_unchanged_and_updated():
    session = make_session()
    repo = MatchRepository(session)
    entity, state = repo.upsert_match(match_data())
    assert state == "created"
    assert entity.league_id == 101
    assert repo.upsert_match(match_data())[1] == "unchanged"
    assert repo.upsert_match(replace(match_data(), match_status="Closed"))[1] == "updated"
    assert entity.match_status == "Closed"


def test_duplicate_odds_is_ignored_but_conflict_preserves_original():
    session = make_session()
    repo = MatchRepository(session)
    match, _ = repo.upsert_match(match_data())
    assert repo.add_odds(match, odds()) == OddsWrite.INSERTED
    assert repo.add_odds(match, odds()) == OddsWrite.DUPLICATE
    assert repo.add_odds(match, odds("2.20")) == OddsWrite.CONFLICT
    assert session.query(OddsSnapshot).one().home_odds == Decimal("2.100")


def test_apply_result_sets_total_and_payout_once():
    session = make_session()
    repo = MatchRepository(session)
    match, _ = repo.upsert_match(match_data())
    result = MatchResultData(7, 2, 1, 3, "H")
    assert repo.apply_result(match, result, Decimal("2.10")) is True
    assert repo.apply_result(match, result, Decimal("2.10")) is False
    stored = session.query(Match).one()
    assert (stored.home_goals, stored.away_goals, stored.total_goals) == (2, 1, 3)
    assert stored.had_result == "H"
