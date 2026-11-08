"""科目汇总：给新前端做侧边栏分组、聊天科目选择。"""

from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.base import get_db
from app.db.models import ChatSession, Document, Question, User

router = APIRouter()


@router.get("/courses")
def list_courses(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"sessions": 0, "questions": 0, "documents": 0}
    )

    rows = db.execute(
        select(ChatSession.course, func.count(ChatSession.id))
        .where(ChatSession.user_id == user.id)
        .group_by(ChatSession.course)
    ).all()
    for name, count in rows:
        counts[(name or "未分类").strip() or "未分类"]["sessions"] = count

    rows = db.execute(
        select(Question.course, func.count(Question.id))
        .where(Question.user_id == user.id)
        .group_by(Question.course)
    ).all()
    for name, count in rows:
        counts[(name or "未分类").strip() or "未分类"]["questions"] = count

    rows = db.execute(
        select(Document.course, func.count(Document.id))
        .where(Document.user_id == user.id)
        .group_by(Document.course)
    ).all()
    for name, count in rows:
        counts[(name or "未分类").strip() or "未分类"]["documents"] = count

    result = [
        {"name": name, **values}
        for name, values in counts.items()
        if name
    ]
    result.sort(key=lambda item: (-item["sessions"], item["name"]))
    return result
