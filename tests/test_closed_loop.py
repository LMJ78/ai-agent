"""站内通知与学习/生活闭环接口。"""

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.timeutil import local_date
from app.db.base import SessionLocal
from app.db.init import DEMO_USERNAME
from app.db.models import CalendarEvent, Habit, HabitLog, NewsItem, Notification, ReviewItem, User
from app.main import app


def _user_id() -> int:
    with SessionLocal() as db:
        value = db.scalar(select(User.id).where(User.username == DEMO_USERNAME))
    assert value is not None
    return value


def test_notifications_unread_and_mark_all() -> None:
    user_id = _user_id()
    prefix = f"W7通知-{uuid.uuid4().hex[:6]}"
    with SessionLocal() as db:
        db.add_all(
            [
                Notification(
                    user_id=user_id,
                    kind="todo",
                    title=f"{prefix} 第一条",
                    body="内容一",
                    link="calendar",
                    dedupe_key=f"{prefix}:1",
                ),
                Notification(
                    user_id=user_id,
                    kind="review",
                    title=f"{prefix} 第二条",
                    body="内容二",
                    link="review",
                    dedupe_key=f"{prefix}:2",
                ),
            ]
        )
        db.commit()

    try:
        with TestClient(app) as client:
            unread = client.get("/api/notifications/unread-count")
            assert unread.status_code == 200
            assert unread.json()["unread"] >= 2

            listed = client.get("/api/notifications", params={"limit": 100})
            assert listed.status_code == 200
            rows = [row for row in listed.json()["items"] if row["title"].startswith(prefix)]
            assert len(rows) == 2

            marked = client.post(f"/api/notifications/{rows[0]['id']}/read")
            assert marked.status_code == 200
            assert marked.json()["read"] is True

            all_read = client.post("/api/notifications/read-all")
            assert all_read.status_code == 200
            after = client.get("/api/notifications/unread-count")
            assert after.status_code == 200
    finally:
        with SessionLocal() as db:
            db.execute(delete(Notification).where(Notification.user_id == user_id, Notification.title.like(f"{prefix}%")))
            db.commit()


def test_review_mastery_and_exam_plan() -> None:
    user_id = _user_id()
    course = f"W7掌握度-{uuid.uuid4().hex[:6]}"
    with SessionLocal() as db:
        db.add_all(
            [
                ReviewItem(
                    user_id=user_id,
                    course=course,
                    chapter="动态规划",
                    question="题一",
                    answer="A",
                    options='["A. 对", "B. 错"]',
                    status="active",
                    next_review_at=datetime.now(timezone.utc) - timedelta(days=1),
                ),
                ReviewItem(
                    user_id=user_id,
                    course=course,
                    chapter="动态规划",
                    question="题二",
                    answer="A",
                    options='["A. 对", "B. 错"]',
                    status="mastered",
                    correct_streak=3,
                    next_review_at=datetime.now(timezone.utc),
                ),
                ReviewItem(
                    user_id=user_id,
                    course=course,
                    chapter="贪心",
                    question="题三",
                    answer="A",
                    options='["A. 对", "B. 错"]',
                    status="active",
                    next_review_at=datetime.now(timezone.utc) + timedelta(days=3),
                ),
            ]
        )
        db.commit()

    try:
        with TestClient(app) as client:
            mastery = client.get("/api/review/mastery", params={"course": course})
            assert mastery.status_code == 200
            rows = mastery.json()
            assert {row["chapter"] for row in rows} == {"动态规划", "贪心"}
            dp = next(row for row in rows if row["chapter"] == "动态规划")
            assert dp["total"] == 2 and dp["mastered"] == 1 and dp["due"] == 1

            plan = client.get(
                "/api/review/plan",
                params={"course": course, "exam_date": (local_date() + timedelta(days=6)).isoformat()},
            )
            assert plan.status_code == 200
            data = plan.json()
            assert data["days"] == 7
            assert data["active"] == 2
            assert data["daily_target"] >= 1
            assert data["weak_chapters"]
    finally:
        with SessionLocal() as db:
            db.execute(delete(ReviewItem).where(ReviewItem.course == course))
            db.commit()


def test_calendar_conflicts_detects_overlap() -> None:
    user_id = _user_id()
    prefix = f"W7冲突-{uuid.uuid4().hex[:6]}"
    start = datetime.now(timezone.utc) + timedelta(days=1)
    with SessionLocal() as db:
        db.add_all(
            [
                CalendarEvent(
                    user_id=user_id,
                    title=f"{prefix} A",
                    start_at=start,
                    end_at=start + timedelta(hours=2),
                    recurrence="none",
                ),
                CalendarEvent(
                    user_id=user_id,
                    title=f"{prefix} B",
                    start_at=start + timedelta(hours=1),
                    end_at=start + timedelta(hours=3),
                    recurrence="none",
                ),
            ]
        )
        db.commit()

    try:
        with TestClient(app) as client:
            response = client.get("/api/calendar/conflicts", params={"days": 7})
            assert response.status_code == 200
            assert any(prefix in pair["first"]["title"] for pair in response.json())
    finally:
        with SessionLocal() as db:
            db.execute(delete(CalendarEvent).where(CalendarEvent.title.like(f"{prefix}%")))
            db.commit()


def test_habit_remind_at_and_news_read_star() -> None:
    user_id = _user_id()
    habit_name = f"W7习惯-{uuid.uuid4().hex[:6]}"
    url = f"https://example.com/{uuid.uuid4().hex}"
    with SessionLocal() as db:
        news = NewsItem(
            user_id=user_id,
            news_date=date.today(),
            category="科技/AI",
            title="测试新闻",
            summary="摘要",
            url=url,
            source="example.com",
        )
        db.add(news)
        db.commit()
        news_id = news.id

    try:
        with TestClient(app) as client:
            created = client.post("/api/habits", json={"name": habit_name, "icon": "💧", "remind_at": "20:30"})
            assert created.status_code == 201
            habit_id = created.json()["id"]
            assert created.json()["remind_at"] == "20:30"

            read = client.post(f"/api/news/{news_id}/read")
            assert read.status_code == 200 and read.json()["read"] is True
            starred = client.post(f"/api/news/{news_id}/star", json={"starred": True})
            assert starred.status_code == 200 and starred.json()["starred"] is True
    finally:
        with SessionLocal() as db:
            habit_ids = db.scalars(select(Habit.id).where(Habit.name == habit_name)).all()
            if habit_ids:
                db.execute(delete(HabitLog).where(HabitLog.habit_id.in_(habit_ids)))
                db.execute(delete(Habit).where(Habit.id.in_(habit_ids)))
            db.execute(delete(NewsItem).where(NewsItem.url == url))
            db.commit()
