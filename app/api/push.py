"""PushPlus 推送通道配置与测试发送。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.base import get_db
from app.db.models import User
from app.services.push import (
    PushError,
    PushNotConfiguredError,
    delete_channel,
    get_channel,
    mask_token,
    send_to_user,
    upsert_channel,
)

router = APIRouter()


class PushChannelIn(BaseModel):
    token: str = Field(min_length=1, max_length=255)
    enabled: bool = True


def _state(channel) -> dict:
    if channel is None:
        return {
            "provider": "pushplus",
            "configured": False,
            "enabled": False,
            "token_masked": "",
        }
    return {
        "provider": channel.provider,
        "configured": bool(channel.token),
        "enabled": channel.enabled,
        "token_masked": mask_token(channel.token),
    }


@router.get("/push/channel")
def read_channel(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return _state(get_channel(db, user.id))


@router.put("/push/channel")
def save_channel(
    payload: PushChannelIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        channel = upsert_channel(db, user.id, payload.token, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _state(channel)


@router.delete("/push/channel")
def remove_channel(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    if not delete_channel(db, user.id):
        raise HTTPException(status_code=404, detail="还没有配置推送通道")
    return {"ok": True}


@router.post("/push/test")
async def test_push(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        await send_to_user(db, user.id, "伴学测试提醒", "推送配置成功，之后待办到点会发到这里。")
    except PushNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PushError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "message": "已发送，请检查微信"}
