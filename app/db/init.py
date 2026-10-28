"""建表 + 初始化 demo 用户。"""

from sqlalchemy import select

from app.db.base import Base, SessionLocal, engine
from app.db.models import User

DEMO_USERNAME = "demo"


def init_db() -> None:
    """建表（已存在则跳过），并确保 demo 用户存在。

    第 5 周加了注册登录后，这里只保留建表逻辑，demo 用户由注册接口创建。
    """
    # 必须先 import models，Base.metadata 才知道有哪些表。
    import app.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

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
