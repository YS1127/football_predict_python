"""竞彩足球 HAD 同步命令入口。

命令层只负责依赖装配、建表、输出汇总和退出码；同步业务全部位于 SyncService，
因此以后增加 HTTP API 时不需要复制任何抓取或入库逻辑。
"""

import argparse
import json
from collections.abc import Sequence

from src.crawler.match_crawler import SportteryClient
from src.database.models import BaseModel
from src.database.mysql import SessionLocal, engine
from src.services.sync_service import SyncService


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器；第一版只提供单次执行的 sync 子命令。"""
    parser = argparse.ArgumentParser(description="同步中国竞彩网 HAD 数据到 MySQL")
    parser.add_subparsers(dest="command", required=True).add_parser(
        "sync", help="同步当前赛程、完整赔率历史和待开奖赛果"
    )
    return parser


def cli(argv: Sequence[str] | None = None, service=None) -> int:
    """执行 CLI 并返回进程退出码。

    `service` 是测试及未来嵌入式调用的注入点。存在任意单场失败时返回 1，
    但仍输出完整汇总，便于调度系统告警和定位需要重试的比赛。
    """
    args = build_parser().parse_args(argv)
    if args.command != "sync":
        raise AssertionError("argparse 应已拒绝未知命令")
    if service is None:
        BaseModel.metadata.create_all(engine)
        service = SyncService(SportteryClient(), SessionLocal)
    summary = service.run()
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    return 1 if summary.failures else 0


def main() -> None:
    """标准模块入口，将业务返回值转换为操作系统退出码。"""
    raise SystemExit(cli())


if __name__ == "__main__":
    main()
