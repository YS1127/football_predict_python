"""竞彩足球 HAD 单次同步编排服务。"""

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.crawler.match_crawler import UpstreamError
from src.database.models import Match
from src.database.repository import MatchRepository, OddsWrite
from src.parsers import ParseError, parse_detail, parse_results, parse_schedule


@dataclass
class SyncSummary:
    """一次同步的机器可读汇总，也是 CLI JSON 输出的数据来源。"""

    matches_created: int = 0
    matches_updated: int = 0
    odds_inserted: int = 0
    results_filled: int = 0
    odds_conflicts: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为只包含 JSON 原生类型的字典。"""
        return asdict(self)


class SyncService:
    """组织赛程发现、详情增量写入和赛果回填。

    `session_factory` 每次调用必须返回新 Session。服务有意不依赖 CLI，未来 HTTP
    handler 可以直接复用 `run()`。单场详情及入库独立捕获异常，因此坏比赛不会阻断其余比赛。
    """

    def __init__(self, client, session_factory: Callable[[], Session]):
        self.client = client
        self.session_factory = session_factory

    def run(self) -> SyncSummary:
        """执行一次完整同步并返回统计；赛程级失败会直接抛出。"""
        summary = SyncSummary()
        schedule = parse_schedule(self.client.fetch_schedule())

        # 先逐场提交基础信息。这样即使后续某场详情接口失败，其他比赛仍能继续，
        # 且该比赛会因缺少比分/奖金在下一次同步中自动进入 pending 集合重试。
        for data in schedule:
            try:
                with self.session_factory() as session, session.begin():
                    _, state = MatchRepository(session).upsert_match(data)
                if state == "created":
                    summary.matches_created += 1
                elif state == "updated":
                    summary.matches_updated += 1
            except Exception as exc:
                self._record_failure(summary, data.official_match_id, "比赛写入失败", exc)

        with self.session_factory() as session:
            pending = MatchRepository(session).pending_matches()
            targets = [(match.official_match_id, match.business_date) for match in pending]

        # 赛果接口按业务日期查询。相同日期只请求一次，避免每场比赛重复访问官网。
        results = {}
        failed_result_dates = set()
        for business_date in sorted({item[1] for item in targets}):
            try:
                results.update(parse_results(self.client.fetch_results(business_date, business_date)))
            except (UpstreamError, ParseError) as exc:
                failed_result_dates.add(business_date)
                for match_id, target_date in targets:
                    if target_date == business_date:
                        self._record_failure(summary, match_id, "赛果查询失败", exc)

        for match_id, business_date in targets:
            try:
                detail_payload = self.client.fetch_detail(match_id)
                snapshots, payout = parse_detail(detail_payload, match_id)
                with self.session_factory() as session, session.begin():
                    match = session.scalar(select(Match).where(Match.official_match_id == match_id))
                    if match is None:
                        raise RuntimeError("数据库中找不到待同步比赛")
                    repo = MatchRepository(session)
                    for snapshot in snapshots:
                        outcome = repo.add_odds(match, snapshot)
                        if outcome == OddsWrite.INSERTED:
                            summary.odds_inserted += 1
                        elif outcome == OddsWrite.CONFLICT:
                            summary.odds_conflicts += 1
                    result = results.get(match_id)
                    if result is not None and payout is not None and repo.apply_result(match, result, payout):
                        summary.results_filled += 1
            except (UpstreamError, ParseError) as exc:
                self._record_failure(summary, match_id, "官网请求失败", exc)
            except Exception as exc:
                self._record_failure(summary, match_id, "单场同步失败", exc)
        return summary

    @staticmethod
    def _record_failure(summary: SyncSummary, match_id: int, context: str, exc: Exception) -> None:
        """记录简短错误；去重可避免同一比赛的同一错误重复出现在汇总中。"""
        failure = {"match_id": match_id, "error": f"{context}: {exc}"}
        if failure not in summary.failures:
            summary.failures.append(failure)
