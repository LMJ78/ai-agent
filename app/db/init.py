"""建表 + 初始化 demo 用户。"""

from sqlalchemy import select

from app.core.constants import SHARED_USER_ID, SHARED_USERNAME
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
            "completed_at": "ALTER TABLE todos ADD COLUMN completed_at DATETIME",
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

        message_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(messages)")
        }
        if "citations" not in message_columns:
            conn.exec_driver_sql(
                "ALTER TABLE messages ADD COLUMN citations TEXT NOT NULL DEFAULT '[]'"
            )

        habit_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(habits)")
        }
        if "remind_at" not in habit_columns:
            conn.exec_driver_sql(
                "ALTER TABLE habits ADD COLUMN remind_at VARCHAR(5) NOT NULL DEFAULT ''"
            )

        news_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(news_items)")
        }
        if "read_at" not in news_columns:
            conn.exec_driver_sql("ALTER TABLE news_items ADD COLUMN read_at DATETIME")
        if "starred" not in news_columns:
            conn.exec_driver_sql(
                "ALTER TABLE news_items ADD COLUMN starred BOOLEAN NOT NULL DEFAULT 0"
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
        shared = db.get(User, SHARED_USER_ID)
        if shared is None:
            db.add(
                User(
                    id=SHARED_USER_ID,
                    username=SHARED_USERNAME,
                    display_name="公共课程资料",
                    role="system",
                    is_active=False,
                )
            )
            db.commit()

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
