"""错题本与间隔复习。

规则不复杂：
- 自测答错 → 进错题本，明天再复习；
- 复习答对 → 连续答对次数 +1，间隔按 3/7/14/30 天拉长；
- 连续答对 3 次 → 标记 mastered，之后不再出现在「今天要复习」。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Quiz, QuizQuestion, ReviewItem


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_interval(streak: int) -> int:
    return {1: 3, 2: 7, 3: 14}.get(streak, 30)


def record_wrong_answer(
    db: Session,
    *,
    user_id: int,
    quiz: Quiz,
    item: QuizQuestion,
    given: str,
) -> ReviewItem:
    """自测提交时调用：答错就写入/更新错题本。"""
    existing = db.scalar(
        select(ReviewItem).where(
            ReviewItem.user_id == user_id,
            ReviewItem.quiz_question_id == item.id,
        )
    )
    if existing is None:
        existing = ReviewItem(
            user_id=user_id,
            course=quiz.course,
            chapter=quiz.chapter,
            question=item.question,
            options=item.options,
            answer=item.answer,
            explanation=item.explanation,
            source=item.source,
            quiz_question_id=item.id,
            wrong_count=1,
            next_review_at=_now() + timedelta(days=1),
        )
        db.add(existing)
    else:
        existing.wrong_count += 1
        existing.correct_streak = 0
        existing.status = "active"
        existing.last_result = "wrong"
        existing.next_review_at = _now() + timedelta(days=1)
    return existing


def review_dict(item: ReviewItem) -> dict:
    import json

    return {
        "id": item.id,
        "course": item.course,
        "chapter": item.chapter,
        "question": item.question,
        "options": json.loads(item.options or "[]"),
        "answer": item.answer,
        "explanation": item.explanation,
        "source": item.source,
        "wrong_count": item.wrong_count,
        "review_count": item.review_count,
        "correct_streak": item.correct_streak,
        "last_result": item.last_result,
        "status": item.status,
        "next_review_at": item.next_review_at.isoformat() if item.next_review_at else "",
        "last_reviewed_at": (
            item.last_reviewed_at.isoformat() if item.last_reviewed_at else ""
        ),
    }


def submit_review(db: Session, item: ReviewItem, given: str) -> dict:
    given = given.strip().upper()[:1]
    is_correct = given == item.answer
    item.review_count += 1
    item.last_reviewed_at = _now()
    item.last_result = "correct" if is_correct else "wrong"
    if is_correct:
        item.correct_streak += 1
        if item.correct_streak >= 3:
            item.status = "mastered"
        item.next_review_at = _now() + timedelta(
            days=_next_interval(item.correct_streak)
        )
    else:
        item.correct_streak = 0
        item.wrong_count += 1
        item.status = "active"
        item.next_review_at = _now() + timedelta(days=1)
    return {
        **review_dict(item),
        "is_correct": is_correct,
        "correct_answer": item.answer,
        "explanation": item.explanation,
    }
