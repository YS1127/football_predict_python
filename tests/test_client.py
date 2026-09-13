import requests
import pytest

from src.crawler.match_crawler import SportteryClient, UpstreamError


class Response:
    def __init__(self, status, payload=None, json_error=None):
        self.status_code = status
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


class Session:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def client(outcomes, sleeps):
    return SportteryClient(
        session=Session(outcomes), timeout=3, retry_limit=2,
        backoff_seconds=0.1, sleeper=sleeps.append,
    )


def test_retries_500_then_returns_json():
    sleeps = []
    api = client([Response(500), Response(200, {"success": True})], sleeps)
    assert api.fetch_schedule() == {"success": True}
    assert sleeps == [0.1]
    assert len(api.session.calls) == 2


def test_does_not_retry_ordinary_400():
    api = client([Response(400)], [])
    with pytest.raises(UpstreamError, match="HTTP 400"):
        api.fetch_schedule()
    assert len(api.session.calls) == 1


def test_rejects_non_json_response():
    api = client([Response(200, json_error=ValueError("html"))], [])
    with pytest.raises(UpstreamError, match="非 JSON"):
        api.fetch_schedule()


def test_retries_network_error():
    api = client([requests.Timeout(), Response(200, {"success": True})], [])
    assert api.fetch_detail(7) == {"success": True}
