import pytest

from src.services.sync_service import SyncSummary
from src.services.task_runner import TaskBusy, TaskRunner


def test_runner_rejects_busy_task():
    runner = TaskRunner(lock_factory=lambda names: False)
    with pytest.raises(TaskBusy):
        runner.run("daily-match-sync", "cli", lambda: SyncSummary())


def test_runner_returns_task_summary():
    runner = TaskRunner(lock_factory=lambda names: True)
    summary = runner.run("result-sync", "http", lambda: SyncSummary(results_filled=2))
    assert summary.results_filled == 2
