"""测试公共设置。

W5 起所有业务接口都要求登录。为了不改动 W1–W4 那批接口测试，
这里默认把 get_current_user 覆盖成 demo 用户；专门测鉴权的用例
可以调用 app.dependency_overrides.pop(get_current_user) 再发请求。
"""

import pytest
from sqlalchemy import select

from app.core.deps import get_current_user
from app.db.base import SessionLocal
from app.db.init import DEMO_USERNAME, init_db
from app.db.models import User
from app.main import app


@pytest.fixture(autouse=True)
def auth_override():
    init_db()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == DEMO_USERNAME))
        assert user is not None

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            yield
        finally:
            app.dependency_overrides.pop(get_current_user, None)
