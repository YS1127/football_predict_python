
"""从项目根目录 .env 和环境变量读取运行配置。"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """MySQL 与官网客户端配置；字段名大小写不敏感。"""
    # Mysql
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    crawler_timeout: int = 30
    crawler_retry_limit: int = 3
    # 重试等待的初始秒数；后续重试按 2 的幂指数退避。
    crawler_backoff_seconds: float = 0.5
    crawler_user_agent: str = "Mozilla/5.0"
    # 历史赔率逐场抓取的固定间隔，避免连续请求给官网造成不必要压力。
    history_odds_request_interval_seconds: float = 1.0
    sporttery_base_url: str = "https://webapi.sporttery.cn/gateway/uniform/football"
    sporttery_referer: str = "https://www.sporttery.cn/jc/jsq/zqspf/"
    sporttery_origin: str = "https://www.sporttery.cn"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    @property
    def database_url(self) -> str:
        """生成 SQLAlchemy 使用的 PyMySQL 连接地址。"""
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
            "?charset=utf8mb4"
        )

settings = Settings()
