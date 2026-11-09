"""用量面板：token、轮次与费用估算。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.base import get_db
from app.db.models import User
from app.services.usage import usage_summary

router = APIRouter()


@router.get("/usage/summary")
def summary(
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return usage_summary(db, user.id, days)
