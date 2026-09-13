"""中国竞彩网足球接口客户端。

本模块只处理 HTTP 通信、有限重试和 JSON 解码，不在这里解释业务字段。
这种边界使解析器可以完全依赖本地样本测试，也便于同步服务在未来被 HTTP 接口复用。
"""

import time
from datetime import date
from typing import Any, Callable

import requests

from src.config.settings import settings


class UpstreamError(RuntimeError):
    """官网请求无法产生可信 JSON 数据时抛出的统一异常。"""


class SportteryClient:
    """封装赛程、赔率历史和赛果三个官网端点。"""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: float | None = None,
        retry_limit: int | None = None,
        backoff_seconds: float | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        """创建客户端；可注入 Session 和 sleeper 以进行无网络、无等待的单元测试。"""
        self.session = session or requests.Session()
        self.timeout = timeout if timeout is not None else settings.crawler_timeout
        self.retry_limit = retry_limit if retry_limit is not None else settings.crawler_retry_limit
        self.backoff_seconds = backoff_seconds if backoff_seconds is not None else settings.crawler_backoff_seconds
        self.sleeper = sleeper
        self.headers = {
            "User-Agent": settings.crawler_user_agent,
            "Accept": "application/json, text/plain, */*",
            "Referer": settings.sporttery_referer,
            "Origin": settings.sporttery_origin,
        }

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行一次逻辑 GET 请求，并仅重试临时性故障。

        网络异常、429 和 5xx 通常可恢复，因此按指数退避重试；普通 4xx、
        非 JSON 或错误的顶层类型代表请求/契约问题，立即失败，避免无意义地冲击官网。
        异常信息刻意不携带响应正文，防止日志意外记录完整敏感响应。
        """
        url = f"{settings.sporttery_base_url}/{path}"
        attempts = self.retry_limit + 1
        for attempt in range(attempts):
            try:
                response = self.session.get(
                    url, params=params, headers=self.headers, timeout=self.timeout
                )
            except requests.RequestException as exc:
                if attempt + 1 == attempts:
                    raise UpstreamError(f"官网网络请求失败: {type(exc).__name__}") from exc
                self.sleeper(self.backoff_seconds * (2 ** attempt))
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 == attempts:
                    raise UpstreamError(f"官网 HTTP {response.status_code}，重试已耗尽")
                self.sleeper(self.backoff_seconds * (2 ** attempt))
                continue
            if response.status_code >= 400:
                raise UpstreamError(f"官网 HTTP {response.status_code}")

            try:
                payload = response.json()
            except ValueError as exc:
                raise UpstreamError("官网返回非 JSON 响应") from exc
            if not isinstance(payload, dict):
                raise UpstreamError("官网 JSON 顶层不是对象")
            return payload
        raise AssertionError("请求重试循环意外结束")

    def fetch_schedule(self) -> dict[str, Any]:
        """获取当前在售 HAD 赛程与最新赔率。"""
        return self._get("getMatchCalculatorV1.qry", {"channel": "c", "poolCode": "had"})

    def fetch_detail(self, match_id: int) -> dict[str, Any]:
        """获取指定官方比赛的完整赔率历史与开奖固定奖金。"""
        return self._get("getFixedBonusV1.qry", {"clientCode": "3001", "matchId": match_id})

    def fetch_results(self, begin: date, end: date) -> dict[str, Any]:
        """获取闭区间内的权威赛果；比分字段为常规时间加伤停补时。"""
        return self._get("getUniformMatchResultV1.qry", {
            "matchBeginDate": begin.isoformat(),
            "matchEndDate": end.isoformat(),
            "leagueId": "",
            "pageSize": 100,
            "pageNo": 1,
            "isFix": 0,
            "matchPage": 1,
            "pcOrWap": 1,
        })


# 保留旧类名作为轻量兼容别名，避免已有调用方突然中断。
MatchCrawler = SportteryClient
