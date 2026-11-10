"""每日新闻接口：只存在 Agent 内部，不推送；保留最近 3 天。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.timeutil import local_date
from app.db.base import get_db
from app.db.models import User
from app.services.news import RETENTION_DAYS, list_news, refresh_news
from app.tools.base import ToolError

router = APIRouter()


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
