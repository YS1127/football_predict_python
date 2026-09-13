import json

from src.main import cli
from src.services.sync_service import SyncSummary


class Service:
    def __init__(self, summary):
        self.summary = summary

    def run(self):
        return self.summary


class Backfill:
    def __init__(self, summary):
        self.summary = summary
        self.arguments = None

    def run(self, start, end):
        self.arguments = (start, end)
        return self.summary


def test_cli_prints_summary_and_returns_zero(capsys):
    code = cli(["sync"], Service(SyncSummary(matches_created=2)))
    assert code == 0
    assert json.loads(capsys.readouterr().out)["matches_created"] == 2


def test_cli_returns_one_when_any_match_failed(capsys):
    summary = SyncSummary(failures=[{"match_id": 7, "error": "失败"}])
    assert cli(["sync"], Service(summary)) == 1
    assert json.loads(capsys.readouterr().out)["failures"][0]["match_id"] == 7


def test_backfill_cli_passes_explicit_date_range(capsys):
    service = Backfill(SyncSummary(days_processed=256))
    code = cli([
        "backfill", "--start", "2026-01-01", "--end", "2026-09-13"
    ], service)
    assert code == 0
    assert tuple(value.isoformat() for value in service.arguments) == (
        "2026-01-01", "2026-09-13"
    )


def test_backfill_odds_cli_passes_explicit_date_range(capsys):
    service = Backfill(SyncSummary(matches_processed=2908))
    code = cli([
        "backfill-odds", "--start", "2026-01-01", "--end", "2026-09-13"
    ], service)
    assert code == 0
    assert tuple(value.isoformat() for value in service.arguments) == (
        "2026-01-01", "2026-09-13"
    )
