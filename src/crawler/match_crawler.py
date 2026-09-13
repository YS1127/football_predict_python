
import  requests

from src.config.settings import settings


class MatchCrawler:

    WEB_URL = "https://www.sporttery.cn/jc/jsq/zqspf/"
    BASE_URL = "https://webapi.sporttery.cn/gateway/uniform/football"

    def get_matches(self) -> dict:
        url = f"{self.BASE_URL}/getMatchCalculatorV1.qry"

        params = {
            "channel": "c",
            "poolCode": "had",
        }

        headers = {
            "User-Agent": settings.crawler_user_agent,
            "Referer": self.WEB_URL,
        }

        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=settings.crawler_timeout,
        )

        return response.json()