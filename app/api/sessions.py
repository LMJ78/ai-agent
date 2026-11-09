"""学习记录：按科目/模式列出会话、回看消息、改名、删除。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.base import get_db
from app.db.models import ChatSession, Message, Question, User

router = APIRouter()


class SessionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    course: str | None = Field(default=None, max_length=64)


def _session_dict(session: ChatSession, message_count: int = 0) -> dict:
    return {
        "id": session.id,
        "title": session.title,
        "mode": session.mode,
        "course": session.course,
        "message_count": message_count,
        "updated_at": session.updated_at.isoformat() if session.updated_at else "",
    }


def _get_own(db: Session, user_id: int, session_id: int) -> ChatSession:
    session = db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
        )
    )
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.get("/sessions")
def list_sessions(
    course: str | None = Query(default=None, description="按科目过滤，例如「算法设计与分析」"),
    mode: Literal["study", "life"] | None = Query(default=None, description="按学习/生活模式过滤"),
    q: str | None = Query(default=None, description="在标题/消息里搜索关键词"),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(ChatSession).where(ChatSession.user_id == user.id)
    if course:
        stmt = stmt.where(ChatSession.course == course)
    if mode:
        stmt = stmt.where(ChatSession.mode == mode)

    keyword = (q or "").strip()
    if keyword:
        stmt = (
            stmt.join(Message, Message.session_id == ChatSession.id)
            .where(
                or_(
                    ChatSession.title.contains(keyword),
                    Message.content.contains(keyword),
                )
            )
            .distinct()
        )

    sessions = db.scalars(
        stmt.order_by(ChatSession.updated_at.desc()).limit(limit)
    ).all()

    counts = {}
    if sessions:
        ids = [s.id for s in sessions]
        rows = db.execute(
            select(Message.session_id, func.count(Message.id))
            .where(Message.session_id.in_(ids))
            .group_by(Message.session_id)
        ).all()
        counts = {session_id: count for session_id, count in rows}

    return [_session_dict(session, counts.get(session.id, 0)) for session in sessions]


@router.get("/sessions/{session_id}/messages")
def get_session_messages(
    session_id: int,
    limit: int = Query(default=200, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session = _get_own(db, user.id, session_id)
    rows = db.scalars(
        select(Message)
        .where(Message.session_id == session.id)
        .order_by(Message.id.asc())
        .limit(limit)
    ).all()
    return {
        "session": _session_dict(session, len(rows)),
        "messages": [
            {
                "id": item.id,
                "role": item.role,
                "content": item.content,
                "created_at": item.created_at.isoformat() if item.created_at else "",
            }
            for item in rows
        ],
    }


@router.patch("/sessions/{session_id}")
def update_session(
    session_id: int,
    payload: SessionUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session = _get_own(db, user.id, session_id)

    if payload.course is not None and payload.course.strip() != session.course:
        message_count = db.scalar(
            select(func.count(Message.id)).where(Message.session_id == session.id)
        )
        if message_count:
            raise HTTPException(
                status_code=409,
                detail="这个会话已经有消息了，不能改科目；请新建一个会话",
            )
        session.course = payload.course.strip()[:64]

    if payload.title is not None and payload.title.strip():
        session.title = payload.title.strip()[:120]

    db.commit()
    db.refresh(session)
    return _session_dict(session)


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session = _get_own(db, user.id, session_id)

    # 题库里的题要继续保留；只解除它和会话的关联，避免外键挡住删除。
    unlinked = db.execute(
        update(Question)
        .where(Question.session_id == session.id, Question.user_id == user.id)
        .values(session_id=None)
    ).rowcount

    db.delete(session)
    db.commit()
    return {"deleted": session_id, "unlinked_questions": unlinked}
