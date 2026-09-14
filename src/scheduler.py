"""独立 APScheduler 进程及模块级定时任务入口。"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config.settings import settings
from src.crawler.match_crawler import SportteryClient
from src.database.mysql import SessionLocal
from src.services.daily_match_sync_service import DailyMatchSyncService
from src.services.result_sync_service import ResultSyncService
from src.services.task_runner import TaskBusy, TaskRunner


def run_daily_match_sync() -> None:
    """供调度器调用的模块级当天赛程任务。"""
    TaskRunner().run("daily-match-sync", "scheduled", lambda: DailyMatchSyncService(
        SportteryClient(), SessionLocal,
        request_interval_seconds=settings.daily_match_detail_interval_seconds,
    ).run(trigger_source="scheduled"))


def run_result_sync() -> None:
    """供调度器调用的模块级赛果回填任务。"""
    TaskRunner().run("result-sync", "scheduled", lambda: ResultSyncService(
        SportteryClient(), SessionLocal
    ).run())


def build_scheduler(config=settings, scheduler_cls=BlockingScheduler):
    """校验配置并注册启用的任务；任务不会在构建阶段执行。"""
    scheduler = scheduler_cls(timezone=config.scheduler_timezone)
    common = {
        "max_instances": 1,
        "coalesce": True,
        "misfire_grace_time": config.scheduler_misfire_grace_seconds,
    }
    if config.daily_match_sync_enabled:
        scheduler.add_job(run_daily_match_sync, CronTrigger.from_crontab(
            config.daily_match_sync_cron, timezone=config.scheduler_timezone
        ), id="daily-match-sync", **common)
    if config.result_sync_enabled:
        scheduler.add_job(run_result_sync, CronTrigger.from_crontab(
            config.result_sync_cron, timezone=config.scheduler_timezone
        ), id="result-sync", **common)
    return scheduler


def run_scheduler() -> None:
    """在前台持续运行调度器，直到进程收到终止信号。"""
    build_scheduler().start()
