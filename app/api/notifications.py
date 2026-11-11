"""站内通知接口。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.base import get_db
from app.db.models import User
from app.services.notifications import (
    list_notifications,
    mark_all_read,
    mark_read,
    notification_dict,
    unread_count,
)

router = APIRouter()


@router.get("/notifications")
def get_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    unread_only: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = list_notifications(db, user.id, limit=limit, unread_only=unread_only)
    return {
        "items": [notification_dict(item) for item in rows],
        "unread": unread_count(db, user.id),
    }


@router.get("/notifications/unread-count")
def get_unread_count(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"unread": unread_count(db, user.id)}


@router.post("/notifications/{notification_id}/read")
def read_notification(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not mark_read(db, user.id, notification_id):
        raise HTTPException(status_code=404, detail="通知不存在")
    return {"id": notification_id, "read": True, "unread": unread_count(db, user.id)}


@router.post("/notifications/read-all")
def read_all(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    count = mark_all_read(db, user.id)
    return {"updated": count, "unread": 0}
