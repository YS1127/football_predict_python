"""定时、CLI 与 HTTP 触发共享的任务运行边界。"""

import logging
import time

from sqlalchemy import text

from src.database.mysql import engine


logger = logging.getLogger(__name__)


class TaskBusy(RuntimeError):
    """全局官网锁或同名任务锁已被其他执行占用。"""


class TaskRunner:
    """在 MySQL advisory lock 保护下执行一个同步任务。"""

    def __init__(self, lock_factory=None):
        self.lock_factory = lock_factory

    def run(self, task_name: str, source: str, operation):
        """运行任务并记录耗时；测试可注入无数据库的锁判定器。"""
        started = time.monotonic()
        if self.lock_factory is not None:
            if not self.lock_factory(("football:upstream", f"football:{task_name}")):
                raise TaskBusy(f"{task_name} 任务正在运行")
            result = operation()
        else:
            result = self._run_with_mysql_locks(task_name, operation)
        logger.info("任务完成 task=%s source=%s elapsed=%.3f", task_name, source, time.monotonic() - started)
        return result

    @staticmethod
    def _run_with_mysql_locks(task_name: str, operation):
        """在同一连接上获取并最终释放全局锁和任务锁。"""
        names = ("football:upstream", f"football:{task_name}")
        acquired = []
        with engine.connect() as connection:
            try:
                for name in names:
                    value = connection.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": name}).scalar_one()
                    if value != 1:
                        raise TaskBusy(f"{task_name} 任务正在运行")
                    acquired.append(name)
                return operation()
            finally:
                for name in reversed(acquired):
                    connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
