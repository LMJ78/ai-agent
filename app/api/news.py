"""每日新闻接口：只存在 Agent 内部，不推送；保留最近 3 天。"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.timeutil import local_date
from app.db.base import get_db
from app.db.models import NewsItem, User
from app.services.news import RETENTION_DAYS, list_news, refresh_news
from app.tools.base import ToolError

router = APIRouter()


class NewsStarIn(BaseModel):
    starred: bool = True


def _own_news(db: Session, user_id: int, news_id: int) -> NewsItem:
    item = db.scalar(
        select(NewsItem).where(
            NewsItem.id == news_id,
            NewsItem.user_id == user_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="新闻不存在")
    return item


def _payload(days: list[dict], warning: str = "") -> dict:
    return {
        "days": days,
        "retention_days": RETENTION_DAYS,
        "warning": warning,
    }


@router.get("/news")
async def get_news(
    days: int = Query(default=RETENTION_DAYS, ge=1, le=RETENTION_DAYS),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    rows = list_news(db, user.id, days=days)
    today = local_date().isoformat()
    if not any(row["date"] == today for row in rows):
        try:
            await refresh_news(db, user.id)
        except ToolError as exc:
            if not rows:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            return _payload(rows, warning=str(exc))
        rows = list_news(db, user.id, days=days)
    return _payload(rows)


@router.post("/news/{news_id}/read")
def mark_news_read(
    news_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    item = _own_news(db, user.id, news_id)
    if item.read_at is None:
        item.read_at = datetime.now(timezone.utc)
        db.commit()
    return {"id": item.id, "read": True}


@router.post("/news/{news_id}/star")
def star_news(
    news_id: int,
    payload: NewsStarIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    item = _own_news(db, user.id, news_id)
    item.starred = payload.starred
    db.commit()
    return {"id": item.id, "starred": item.starred}


@router.post("/news/refresh")
async def refresh(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        added = await refresh_news(db, user.id, force=True)
    except ToolError as exc:
        status = 503 if "TAVILY_API_KEY" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if added == 0:
        raise HTTPException(status_code=502, detail="这次没有抓到新闻，请稍后再试")
    return _payload(list_news(db, user.id))
