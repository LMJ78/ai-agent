"""错题本：按科目/章节查看，按间隔复习。"""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.base import get_db
from app.db.models import ReviewItem, User
from app.services.review import (
    add_manual_item,
    review_dict,
    submit_review,
    submit_self_check,
)

router = APIRouter()


class ReviewItemIn(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    answer: str = Field(default="", max_length=8000)
    explanation: str = Field(default="", max_length=16000)
    course: str = Field(default="", max_length=64)
    chapter: str = Field(default="", max_length=64)
    source: str = Field(default="", max_length=255)
    options: list[str] = Field(default_factory=list, max_length=8)


class ReviewAnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=4)


class ReviewSelfCheckIn(BaseModel):
    result: Literal["correct", "wrong"]


@router.get("/review/items")
def list_review_items(
    course: str | None = Query(default=None),
    status: str | None = Query(default=None),
    due_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(ReviewItem).where(ReviewItem.user_id == user.id)
    if course:
        stmt = stmt.where(ReviewItem.course == course)
    if status:
        stmt = stmt.where(ReviewItem.status == status)
    if due_only:
        stmt = stmt.where(
            ReviewItem.status == "active",
            ReviewItem.next_review_at <= datetime.now(timezone.utc),
        )
    rows = db.scalars(
        stmt.order_by(ReviewItem.next_review_at.asc(), ReviewItem.id.desc()).limit(limit)
    ).all()
    return [review_dict(item) for item in rows]


@router.get("/review/stats")
def review_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    base = select(func.count(ReviewItem.id)).where(ReviewItem.user_id == user.id)
    active = db.scalar(base.where(ReviewItem.status == "active")) or 0
    mastered = db.scalar(base.where(ReviewItem.status == "mastered")) or 0
    due = (
        db.scalar(
            base.where(
                ReviewItem.status == "active",
                ReviewItem.next_review_at <= now,
            )
        )
        or 0
    )
    rows = db.execute(
        select(ReviewItem.course, func.count(ReviewItem.id))
        .where(ReviewItem.user_id == user.id)
        .group_by(ReviewItem.course)
    ).all()
    return {
        "active": active,
        "mastered": mastered,
        "due": due,
        "by_course": [{"course": course or "未分类", "count": count} for course, count in rows],
    }


@router.post("/review/items", status_code=201)
def create_review_item(
    payload: ReviewItemIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    item, created = add_manual_item(
        db,
        user_id=user.id,
        question=payload.question,
        answer=payload.answer,
        explanation=payload.explanation,
        course=payload.course,
        chapter=payload.chapter,
        source=payload.source,
        options=payload.options,
    )
    db.commit()
    return {**review_dict(item), "created": created}


@router.post("/review/items/{item_id}/answer")
def answer_review_item(
    item_id: int,
    payload: ReviewAnswerIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    item = db.scalar(
        select(ReviewItem).where(
            ReviewItem.id == item_id,
            ReviewItem.user_id == user.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="复习卡不存在")
    if not review_dict(item)["options"]:
        raise HTTPException(status_code=400, detail="这是回忆卡，请用「我记住了/没记住」自评")
    result = submit_review(db, item, payload.answer)
    db.commit()
    return result


@router.post("/review/items/{item_id}/self-check")
def self_check_review_item(
    item_id: int,
    payload: ReviewSelfCheckIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    item = db.scalar(
        select(ReviewItem).where(
            ReviewItem.id == item_id,
            ReviewItem.user_id == user.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="复习卡不存在")
    if review_dict(item)["options"]:
        raise HTTPException(status_code=400, detail="选择题请提交具体答案")
    result = submit_self_check(db, item, payload.result)
    db.commit()
    return result


@router.delete("/review/items/{item_id}")
def delete_review_item(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    item = db.scalar(
        select(ReviewItem).where(
            ReviewItem.id == item_id,
            ReviewItem.user_id == user.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="复习卡不存在")
    db.delete(item)
    db.commit()
    return {"deleted": item_id}
