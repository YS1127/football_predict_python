from datetime import date

from src.services.daily_match_sync_service import DailyMatchSyncService
from src.services.result_sync_service import ResultSyncService


def test_daily_match_task_never_calls_results():
    class Client:
        def fetch_schedule(self):
            return {"success": True, "errorCode": "0", "value": {"matchInfoList": []}}
        def fetch_results(self, *_):
            raise AssertionError("当天任务禁止查询赛果")

    summary = DailyMatchSyncService(Client(), lambda: None, record_sync=False).run(date(2026, 9, 13))
    assert summary.matches_processed == 0


def test_result_task_defaults_to_previous_china_day():
    captured = []
    service = ResultSyncService(object(), lambda: None, target_loader=lambda cutoff: captured.append(cutoff) or [])
    service.run(date(2026, 9, 12))
    assert captured == [date(2026, 9, 12)]
