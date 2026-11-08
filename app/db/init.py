"""建表 + 初始化 demo 用户。"""

from sqlalchemy import select

from app.db.base import Base, SessionLocal, engine
from app.db.models import User

DEMO_USERNAME = "demo"


def _ensure_columns() -> None:
    """给已经存在的 SQLite 表补新列。

    项目没有引入 Alembic，W4 只加了三列；用 PRAGMA + ALTER 足够，
    而且重复执行是安全的。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(todos)")}
        additions = {
            "remind_at": "ALTER TABLE todos ADD COLUMN remind_at DATETIME",
            "reminded_at": "ALTER TABLE todos ADD COLUMN reminded_at DATETIME",
            "remind_attempts": (
                "ALTER TABLE todos ADD COLUMN remind_attempts INTEGER NOT NULL DEFAULT 0"
            ),
        }
        for name, statement in additions.items():
            if name not in columns:
                conn.exec_driver_sql(statement)

        question_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(questions)")
        }
        if "original_filename" not in question_columns:
            conn.exec_driver_sql(
                "ALTER TABLE questions ADD COLUMN original_filename VARCHAR(255) "
                "NOT NULL DEFAULT ''"
            )


def init_db() -> None:
    """建表（已存在则跳过），并确保 demo 用户存在。

    第 5 周加了注册登录后，这里只保留建表逻辑，demo 用户由注册接口创建。
    """
    # 必须先 import models，Base.metadata 才知道有哪些表。
    import app.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_columns()

    with SessionLocal() as db:
        exists = db.scalar(select(User).where(User.username == DEMO_USERNAME))
        if exists is None:
            db.add(
                User(
                    username=DEMO_USERNAME,
                    display_name="演示同学",
                    role="admin",
                )
            )
            db.commit()
