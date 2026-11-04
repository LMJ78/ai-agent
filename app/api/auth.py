"""注册 / 登录 / 当前用户。

注册必须带邀请码；登录返回 7 天有效的 JWT。
"""

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import get_current_user
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.db.base import get_db
from app.db.models import InviteCode, User

router = APIRouter()

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=72)
    display_name: str = Field(default="", max_length=64)
    invite_code: str = Field(min_length=1, max_length=64)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=72)


def _user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.role,
        "created_at": user.created_at.isoformat() if user.created_at else "",
    }


def _auth_response(user: User) -> dict:
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "expires_in": settings.jwt_expire_days * 24 * 3600,
        "user": _user_dict(user),
    }


def _utc_naive_now() -> datetime:
    # SQLite 读出来的 datetime 通常不带 tzinfo，比较前统一成 naive UTC。
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> dict:
    username = payload.username.strip().lower()
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(
            status_code=400,
            detail="用户名只能包含字母、数字、下划线，长度 3–32 位",
        )

    exists = db.scalar(select(User).where(User.username == username))
    if exists is not None:
        raise HTTPException(status_code=409, detail="这个用户名已经被注册了")

    code_value = payload.invite_code.strip().upper()
    invite = db.scalar(select(InviteCode).where(InviteCode.code == code_value))
    if invite is None:
        raise HTTPException(status_code=400, detail="邀请码无效，请找管理员要一个")
    if invite.expires_at is not None and invite.expires_at < _utc_naive_now():
        raise HTTPException(status_code=400, detail="邀请码已过期，请找管理员要一个新的")
    if invite.used_count >= invite.max_uses:
        raise HTTPException(status_code=400, detail="邀请码已经用完了")

    user = User(
        username=username,
        display_name=payload.display_name.strip() or username,
        password_hash=hash_password(payload.password),
        role="user",
        is_active=True,
    )
    db.add(user)
    invite.used_count += 1
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="注册失败：用户名或邀请码冲突") from exc
    db.refresh(user)
    return _auth_response(user)


@router.post("/auth/login")
def login(payload: LoginIn, db: Session = Depends(get_db)) -> dict:
    username = payload.username.strip().lower()
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码不对",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")
    return _auth_response(user)


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return _user_dict(user)


@router.post("/auth/logout")
def logout(user: User = Depends(get_current_user)) -> dict:
    # JWT 是无状态的：服务端不维护 session，客户端删掉 token 即可。
    return {"ok": True, "message": "已退出登录"}
