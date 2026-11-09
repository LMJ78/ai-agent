"""用户设置：早晚简报 / 新闻主题 / 提醒时间。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.base import get_db
from app.db.models import User, UserSettings
from app.services.briefs import (
    build_evening_review,
    build_morning_brief,
    get_or_create_settings,
)
from app.services.push import PushError, PushNotConfiguredError, send_to_user

router = APIRouter()


class SettingsIn(BaseModel):
    morning_enabled: bool = False
    morning_time: str = Field(default="07:30", pattern=r"^\d{2}:\d{2}$")
    evening_enabled: bool = False
    evening_time: str = Field(default="21:30", pattern=r"^\d{2}:\d{2}$")
    news_topics: str = Field(default="", max_length=255)


def _dict(cfg: UserSettings) -> dict:
    return {
        "morning_enabled": cfg.morning_enabled,
        "morning_time": cfg.morning_time,
        "evening_enabled": cfg.evening_enabled,
        "evening_time": cfg.evening_time,
        "news_topics": cfg.news_topics,
        "timezone": cfg.timezone,
    }


@router.get("/settings")
def read_settings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _dict(get_or_create_settings(db, user.id))


@router.put("/settings")
def update_settings(
    payload: SettingsIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    cfg = get_or_create_settings(db, user.id)
    for key, value in payload.model_dump().items():
        setattr(cfg, key, value)
    db.commit()
    db.refresh(cfg)
    return _dict(cfg)


@router.post("/settings/brief/test")
async def test_brief(
    kind: str = "morning",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if kind not in ("morning", "evening"):
        raise HTTPException(status_code=400, detail="kind 只能是 morning 或 evening")
    cfg = get_or_create_settings(db, user.id)
    if kind == "morning":
        title, content = await build_morning_brief(db, user, cfg)
    else:
        title, content = await build_evening_review(db, user, cfg)
    try:
        await send_to_user(db, user.id, title, content)
    except PushNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PushError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"sent": True, "title": title, "preview": content[:300]}
