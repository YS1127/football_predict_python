from datetime import date
import warnings

# FastAPI 0.139 的兼容导入会提示未来迁移到 httpx2。必须在导入 TestClient
# 之前局部过滤，否则警告会在 pytestmark 生效前产生。
warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient

from src.api import create_app
from src.crawler.match_crawler import UpstreamError


class FakeClient:
    """按端点返回固定官网样本，确保 API 测试完全不访问网络。"""

    def __init__(self, fixtures, failure=None):
        self.fixtures = fixtures
        self.failure = failure
        self.result_arguments = None

    def fetch_schedule(self):
        if self.failure:
            raise self.failure
        return self.fixtures["schedule"]

    def fetch_detail(self, match_id):
        if self.failure:
            raise self.failure
        return self.fixtures["detail"]

    def fetch_results(self, begin, end):
        if self.failure:
            raise self.failure
        self.result_arguments = (begin, end)
        return self.fixtures["results"]


def make_client(load_fixture, failure=None):
    upstream = FakeClient({
        "schedule": load_fixture("schedule.json"),
        "detail": load_fixture("detail.json"),
        "results": load_fixture("results.json"),
    }, failure=failure)
    return TestClient(create_app(lambda: upstream)), upstream


def test_schedule_returns_normalized_matches(load_fixture):
    client, _ = make_client(load_fixture)
    response = client.get("/api/schedule")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"][0]["official_match_id"] == 2041387
    assert body["data"][0]["league_id"] == 2068446
    assert body["data"][0]["kickoff_at"] == "2026-09-11T23:45:00"


def test_detail_returns_normalized_odds_and_payout(load_fixture):
    client, _ = make_client(load_fixture)
    response = client.get("/api/matches/2041387/detail")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["official_match_id"] == 2041387
    assert data["payout"] == "1.37"
    assert data["odds_snapshots"][0]["home"] == "4.95"


def test_results_validates_dates_and_returns_normalized_list(load_fixture):
    client, upstream = make_client(load_fixture)
    response = client.get("/api/results?begin=2026-09-11&end=2026-09-12")
    assert response.status_code == 200
    assert response.json()["data"][0]["had_result"] == "A"
    assert upstream.result_arguments == (date(2026, 9, 11), date(2026, 9, 12))


def test_results_rejects_more_than_31_days(load_fixture):
    client, _ = make_client(load_fixture)
    response = client.get("/api/results?begin=2026-01-01&end=2026-02-02")
    assert response.status_code == 422
    assert response.json()["detail"] == "日期范围最多为 31 天"


def test_upstream_failure_is_mapped_to_502(load_fixture):
    client, _ = make_client(load_fixture, UpstreamError("官网 HTTP 500，重试已耗尽"))
    response = client.get("/api/schedule")
    assert response.status_code == 502
    assert response.json() == {
        "success": False,
        "error": "官网 HTTP 500，重试已耗尽",
    }
