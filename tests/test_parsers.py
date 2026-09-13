from decimal import Decimal

import pytest

from src.parsers import ParseError, parse_detail, parse_historical_schedule, parse_results, parse_schedule


def test_schedule_parses_had_match(load_fixture):
    match = parse_schedule(load_fixture("schedule.json"))[0]
    assert (match.official_match_id, match.match_number) == (2041387, "周五002")
    assert match.league_id == 2068446
    assert match.match_date.isoformat() == "2026-09-11"
    assert match.is_valid is True
    assert match.kickoff_at.isoformat(sep=" ") == "2026-09-11 23:45:00"


def test_detail_parses_every_had_snapshot_and_payout(load_fixture):
    odds, payout = parse_detail(load_fixture("detail.json"), 2041387)
    assert [(x.home, x.draw, x.away) for x in odds] == [
        (Decimal("4.95"), Decimal("4.05"), Decimal("1.47")),
        (Decimal("5.75"), Decimal("4.45"), Decimal("1.37")),
    ]
    assert payout == Decimal("1.37")


def test_result_uses_regular_time_score(load_fixture):
    result = parse_results(load_fixture("results.json"))[2041387]
    assert (result.home_goals, result.away_goals, result.total_goals) == (1, 3, 4)
    assert result.had_result == "A"


def test_result_derives_had_when_upstream_omits_win_flag(load_fixture):
    """部分官网已完场记录没有 winFlag，比分本身仍足以确定非让球赛果。"""
    payload = load_fixture("results.json")
    del payload["value"]["matchResult"][0]["winFlag"]
    result = parse_results(payload)[2041387]
    assert result.had_result == "A"


def test_invalid_match_does_not_block_valid_results_on_same_day(load_fixture):
    payload = load_fixture("results.json")
    payload["value"]["matchResult"].append({
        "matchId": 9,
        "matchResultStatus": "2",
        "poolStatus": "Payout",
        "sectionsNo999": "无效场次",
    })
    results = parse_results(payload)
    assert list(results) == [2041387]


def test_historical_schedule_keeps_exact_date_and_unknown_kickoff(load_fixture):
    match = parse_historical_schedule(load_fixture("historical_results.json"))[0]
    assert match.official_match_id == 2036530
    assert match.business_date.isoformat() == "2026-01-01"
    assert match.match_date.isoformat() == "2026-01-01"
    assert match.kickoff_at is None
    assert match.is_valid is True
    assert match.sale_status is None


def test_historical_schedule_marks_invalid_match(load_fixture):
    payload = load_fixture("historical_results.json")
    payload["value"]["matchResult"][0]["sectionsNo999"] = "无效场次"
    match = parse_historical_schedule(payload)[0]
    assert match.is_valid is False


def test_schedule_rejects_missing_required_field(load_fixture):
    payload = load_fixture("schedule.json")
    del payload["value"]["matchInfoList"][0]["subMatchList"][0]["matchId"]
    with pytest.raises(ParseError, match="matchId"):
        parse_schedule(payload)
