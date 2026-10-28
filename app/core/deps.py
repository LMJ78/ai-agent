"""FastAPI 依赖：数据库 Session、当前用户。

第 1 周的「当前用户」是写死的 demo。
第 5 周只需要把 get_current_user 换成「解析 JWT」，其他接口一行都不用改。
"""

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.init import DEMO_USERNAME
from app.db.models import User


def get_current_user(db: Session = Depends(get_db)) -> User:
    user = db.scalar(select(User).where(User.username == DEMO_USERNAME))
    if user is None:
        raise HTTPException(
            status_code=500,
            detail="演示用户不存在，请确认应用启动时执行了 init_db()",
        )
    return user
