"""只读数据工具与公共课程资料检索的测试。"""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.constants import SHARED_USER_ID
from app.db.base import SessionLocal
from app.db.models import (
    CalendarEvent,
    Chunk,
    Document,
    Habit,
    HabitLog,
    NewsItem,
    ReviewItem,
    UsageDaily,
    User,
)
from app.rag.retriever import search_chunks
from app.rag.tokenizer import tokenize
from app.services.usage import record_usage
from app.tools import execute_tool_full


def _run(name: str, user_id: int, arguments: dict):
    return asyncio.run(execute_tool_full(name, __import__("json").dumps(arguments), user_id))


def _make_user() -> int:
    with SessionLocal() as db:
        user = User(
            username=f"tooltest-{uuid.uuid4().hex[:8]}",
            display_name="工具测试",
            password_hash="",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def _cleanup(user_id: int) -> None:
    with SessionLocal() as db:
        db.execute(delete(ReviewItem).where(ReviewItem.user_id == user_id))
        db.execute(delete(CalendarEvent).where(CalendarEvent.user_id == user_id))
        habit_ids = db.scalars(select(Habit.id).where(Habit.user_id == user_id)).all()
        if habit_ids:
            db.execute(delete(HabitLog).where(HabitLog.habit_id.in_(habit_ids)))
            db.execute(delete(Habit).where(Habit.user_id == user_id))
        db.execute(delete(NewsItem).where(NewsItem.user_id == user_id))
        db.execute(delete(UsageDaily).where(UsageDaily.user_id == user_id))
        db.execute(delete(User).where(User.id == user_id))
        db.commit()


def test_shared_course_chunks_are_visible_to_other_users() -> None:
    prefix = f"共享检索-{uuid.uuid4().hex[:6]}"
    with SessionLocal() as db:
        doc = Document(
            user_id=SHARED_USER_ID,
            course=prefix,
            chapter="ch99",
            filename="共享测试课件.pptx",
            status="ready",
        )
        db.add(doc)
        db.flush()
        text = "共享课程资料里的动态规划状态转移方程测试"
        db.add(
            Chunk(
                user_id=SHARED_USER_ID,
                document_id=doc.id,
                course=prefix,
                chapter="ch99",
                filename=doc.filename,
                location="第 1 张幻灯片",
                ordinal=1,
                text=text,
                tokens=" ".join(tokenize(text)),
                token_count=len(tokenize(text)),
            )
        )
        db.commit()
        document_id = doc.id

    try:
        results = search_chunks(2, "动态规划状态转移", course=prefix)
        assert results
        assert results[0].document_id == document_id
    finally:
        with SessionLocal() as db:
            db.execute(delete(Chunk).where(Chunk.document_id == document_id))
            db.execute(delete(Document).where(Document.id == document_id))
            db.commit()


def test_calendar_tool_lists_upcoming_events() -> None:
    user_id = _make_user()
    title = f"工具日程-{uuid.uuid4().hex[:6]}"
    try:
        with SessionLocal() as db:
            start = datetime.now(timezone.utc) + timedelta(hours=2)
            db.add(
                CalendarEvent(
                    user_id=user_id,
                    title=title,
                    location="实验楼-302",
                    start_at=start,
                    end_at=start + timedelta(hours=2),
                )
            )
            db.commit()
        result = _run("calendar", user_id, {"days": 3})
        assert title in result.text
        assert "实验楼-302" in result.text
    finally:
        _cleanup(user_id)


def test_review_tool_reports_due_and_detail() -> None:
    user_id = _make_user()
    try:
        with SessionLocal() as db:
            item = ReviewItem(
                user_id=user_id,
                course="算法设计与分析",
                chapter="动态规划",
                question="0-1 背包的状态转移方程？",
                options="[]",
                answer="dp[i][j] = max(dp[i-1][j], dp[i-1][j-w]+v)",
                explanation="不选/选第 i 个物品。",
                next_review_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
            db.add(item)
            db.commit()
            item_id = item.id

        stats = _run("review", user_id, {"action": "stats"})
        assert "今天该复习 1 道" in stats.text
        due = _run("review", user_id, {"action": "due"})
        assert "0-1 背包" in due.text
        detail = _run("review", user_id, {"action": "get", "item_id": item_id})
        assert "dp[i][j]" in detail.text
    finally:
        _cleanup(user_id)


def test_habits_tool_lists_today_status() -> None:
    user_id = _make_user()
    try:
        with SessionLocal() as db:
            habit = Habit(user_id=user_id, name="工具测试喝水", icon="💧")
            db.add(habit)
            db.flush()
            db.add(HabitLog(habit_id=habit.id, user_id=user_id, log_date=date.today()))
            db.commit()
        result = _run("habits", user_id, {})
        assert "工具测试喝水" in result.text
        assert "✅" in result.text
        assert "连续 1 天" in result.text
    finally:
        _cleanup(user_id)


def test_news_tool_returns_citations() -> None:
    user_id = _make_user()
    title = f"工具新闻-{uuid.uuid4().hex[:6]}"
    try:
        with SessionLocal() as db:
            db.add(
                NewsItem(
                    user_id=user_id,
                    news_date=date.today(),
                    category="科技/AI",
                    title=title,
                    summary="新闻摘要",
                    url="https://example.com/tool-news",
                    source="example.com",
                )
            )
            db.commit()
        result = _run("news", user_id, {"days": 1})
        assert title in result.text
        assert result.citations
        assert result.citations[0]["url"] == "https://example.com/tool-news"
    finally:
        _cleanup(user_id)


def test_usage_tool_summarizes_today() -> None:
    user_id = _make_user()
    try:
        with SessionLocal() as db:
            record_usage(db, user_id, 1200, 300)
            db.commit()
        result = _run("usage", user_id, {"days": 7})
        assert "1 轮" in result.text
        assert "1200 tokens" in result.text
        assert "300 tokens" in result.text
    finally:
        _cleanup(user_id)
