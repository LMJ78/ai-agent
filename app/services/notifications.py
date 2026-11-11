"""站内通知：所有该提醒用户的事情先落库，再决定要不要走 PushPlus。

这样没配置推送、或者推送失败时，用户仍然能在 Agent 里看到，不会“一下过去”。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import Notification


def create_notification(
    db: Session,
    *,
    user_id: int,
    kind: str,
    title: str,
    body: str = "",
    link: str = "",
    dedupe_key: str | None = None,
) -> Notification | None:
    """写一条通知；dedupe_key 相同则忽略，返回 None。

    不 commit，由调用方决定事务边界；这样简报/提醒可以和自己的状态一起提交。
    """
    key = dedupe_key[:255] if dedupe_key else None
    if key:
        exists = db.scalar(
            select(Notification.id).where(
                Notification.user_id == user_id,
                Notification.dedupe_key == key,
            )
        )
        if exists is not None:
            return None

    values = {
        "user_id": user_id,
        "kind": kind[:32],
        "title": title[:255],
        "body": body,
        "link": link[:255],
        "dedupe_key": key,
        "created_at": datetime.now(timezone.utc),
    }
    if key:
        stmt = (
            sqlite_insert(Notification)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
        )
        result = db.execute(stmt)
        if not result.rowcount:
            return None
    if key:
        row = db.scalar(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.dedupe_key == key,
            )
        )
    else:
        row = Notification(**values)
        db.add(row)
        db.flush()
    return row


def unread_count(db: Session, user_id: int) -> int:
    return int(
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
        )
        or 0
    )


def list_notifications(
    db: Session, user_id: int, *, limit: int = 50, unread_only: bool = False
) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list(
        db.scalars(stmt.order_by(Notification.id.desc()).limit(max(1, min(limit, 200)))).all()
    )


def mark_read(db: Session, user_id: int, notification_id: int) -> bool:
    row = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
    )
    if row is None:
        return False
    if row.read_at is None:
        row.read_at = datetime.now(timezone.utc)
        db.commit()
    return True


def mark_all_read(db: Session, user_id: int) -> int:
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    db.commit()
    return int(result.rowcount or 0)


def notification_dict(item: Notification) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "title": item.title,
        "body": item.body,
        "link": item.link,
        "read": item.read_at is not None,
        "created_at": item.created_at.isoformat() if item.created_at else "",
    }
