"""竞彩足球 HAD 同步命令入口。

命令层只负责依赖装配、建表、输出汇总和退出码；同步业务全部位于 SyncService，
因此以后增加 HTTP API 时不需要复制任何抓取或入库逻辑。
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date

from src.crawler.match_crawler import SportteryClient
from src.config.settings import settings
from src.database.models import BaseModel
from src.database.mysql import SessionLocal, engine
from src.services.sync_service import BackfillOddsService, BackfillService, SyncService


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器；第一版只提供单次执行的 sync 子命令。"""
    parser = argparse.ArgumentParser(description="同步中国竞彩网 HAD 数据到 MySQL")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "sync", help="同步当前赛程、完整赔率历史和待开奖赛果"
    )
    backfill = commands.add_parser("backfill", help="按日期范围回填历史 HAD 赛程和赛果")
    backfill.add_argument("--start", type=date.fromisoformat, required=True, help="开始日期 YYYY-MM-DD")
    backfill.add_argument("--end", type=date.fromisoformat, required=True, help="结束日期 YYYY-MM-DD")
    odds = commands.add_parser("backfill-odds", help="为历史有效比赛补齐完整 HAD 赔率")
    odds.add_argument("--start", type=date.fromisoformat, required=True, help="开始日期 YYYY-MM-DD")
    odds.add_argument("--end", type=date.fromisoformat, required=True, help="结束日期 YYYY-MM-DD")
    return parser


def cli(argv: Sequence[str] | None = None, service=None) -> int:
    """执行 CLI 并返回进程退出码。

    `service` 是测试及未来嵌入式调用的注入点。存在任意单场失败时返回 1，
    但仍输出完整汇总，便于调度系统告警和定位需要重试的比赛。
    """
    args = build_parser().parse_args(argv)
    if service is None:
        BaseModel.metadata.create_all(engine)
        if args.command == "sync":
            service = SyncService(SportteryClient(), SessionLocal)
        elif args.command == "backfill":
            service = BackfillService(SportteryClient(), SessionLocal)
        else:
            def progress(processed: int, total: int) -> None:
                """每 50 场或结束时向 stderr 输出进度，不污染 stdout 的 JSON。"""
                if processed % 50 == 0 or processed == total:
                    print(f"历史赔率进度: {processed}/{total}", file=sys.stderr, flush=True)

            service = BackfillOddsService(
                SportteryClient(),
                SessionLocal,
                progress=progress,
                request_interval_seconds=settings.history_odds_request_interval_seconds,
            )
    summary = service.run() if args.command == "sync" else service.run(args.start, args.end)
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    return 1 if summary.failures else 0


def main() -> None:
    """标准模块入口，将业务返回值转换为操作系统退出码。"""
    raise SystemExit(cli())


if __name__ == "__main__":
    main()
