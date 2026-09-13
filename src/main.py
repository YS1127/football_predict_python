import json

from sqlalchemy import text

from src.crawler.match_crawler import MatchCrawler
from src.database.mysql import engine


def test_mysql():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print(result.scalar())

def main():
    crawler = MatchCrawler()

    data = crawler.get_matches()

    print(json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
    ))

if __name__ == '__main__':
    main()