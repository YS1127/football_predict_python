"""生产 MySQL 引擎、Session 工厂和声明式模型基类。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from src.config.settings import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False,
)


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)

class BaseModel(DeclarativeBase):
    """项目所有 SQLAlchemy 模型共享的声明式基类。"""

    pass
