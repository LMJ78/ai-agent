"""数据库连接与 Session 管理。

第 1 周用 SQLite 就够：单文件、免安装。
记得开 WAL，后面 10 个人同时用也不容易锁库。
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATA_DIR, settings

DATA_DIR.mkdir(parents=True, exist_ok=True)

IS_SQLITE = settings.database_url.startswith("sqlite")


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


engine = create_engine(
    settings.database_url,
    # SQLite 默认不允许跨线程使用连接，FastAPI 会在线程池里跑同步代码，所以关掉检查。
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    pool_pre_ping=True,
)

if IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        """每条新连接都设置 WAL 和外键约束。"""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个数据库 Session，用完自动关闭。"""
    with SessionLocal() as db:
        yield db
