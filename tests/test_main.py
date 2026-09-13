import json

from src.main import cli
from src.services.sync_service import SyncSummary


class Service:
    def __init__(self, summary):
        self.summary = summary

    def run(self):
        return self.summary


def test_cli_prints_summary_and_returns_zero(capsys):
    code = cli(["sync"], Service(SyncSummary(matches_created=2)))
    assert code == 0
    assert json.loads(capsys.readouterr().out)["matches_created"] == 2


def test_cli_returns_one_when_any_match_failed(capsys):
    summary = SyncSummary(failures=[{"match_id": 7, "error": "失败"}])
    assert cli(["sync"], Service(summary)) == 1
    assert json.loads(capsys.readouterr().out)["failures"][0]["match_id"] == 7
