"""W6 新功能：错题本、日程、习惯、简报设置、用量。"""

import asyncio
import json
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.init import DEMO_USERNAME
from app.agent.prompts import build_system_prompt
from app.db.models import (
    CalendarEvent,
    Chunk,
    Document,
    Habit,
    HabitLog,
    Quiz,
    QuizQuestion,
    ReviewItem,
    User,
)
from app.main import app
from app.rag.tokenizer import tokenize
from app.services.calendar import parse_ics
from app.services.reminders import scan_due_events
from app.services.usage import record_usage
from app.tools import execute_tool_full


def _user_id() -> int:
    with SessionLocal() as db:
        value = db.scalar(select(User.id).where(User.username == DEMO_USERNAME))
    assert value is not None
    return value


def _cleanup(prefix: str) -> None:
    with SessionLocal() as db:
        db.execute(delete(ReviewItem).where(ReviewItem.course.like(f"{prefix}%")))
        db.execute(delete(CalendarEvent).where(CalendarEvent.title.like(f"{prefix}%")))
        habit_ids = db.scalars(select(Habit.id).where(Habit.name.like(f"{prefix}%"))).all()
        if habit_ids:
            db.execute(delete(HabitLog).where(HabitLog.habit_id.in_(habit_ids)))
            db.execute(delete(Habit).where(Habit.id.in_(habit_ids)))
        db.commit()


def test_review_flow_from_wrong_quiz_answer() -> None:
    prefix = f"W6错题-{uuid.uuid4().hex[:6]}"
    user_id = _user_id()
    _cleanup(prefix)

    with SessionLocal() as db:
        quiz = Quiz(user_id=user_id, course=prefix, chapter="动态规划")
        db.add(quiz)
        db.flush()
        item = QuizQuestion(
            quiz_id=quiz.id,
            user_id=user_id,
            ordinal=1,
            question="0-1 背包的状态转移方程是？",
            options=json.dumps(["A. dp[i][j]=...", "B. 贪心", "C. 排序", "D. 暴力"]),
            answer="A",
            explanation="保留前 i 个物品、容量 j 的最优值。",
        )
        db.add(item)
        db.commit()
        quiz_id, item_id = quiz.id, item.id

    try:
        with TestClient(app) as client:
            submitted = client.post(
                f"/api/quizzes/{quiz_id}/submit",
                json={"answers": {str(item_id): "B"}},
            )
            assert submitted.status_code == 200
            assert submitted.json()["wrong_added"] == 1

            listed = client.get("/api/review/items", params={"course": prefix})
            assert listed.status_code == 200
            rows = listed.json()
            assert len(rows) == 1
            assert rows[0]["wrong_count"] == 1

            answered = client.post(
                f"/api/review/items/{rows[0]['id']}/answer", json={"answer": "A"}
            )
            assert answered.status_code == 200
            assert answered.json()["is_correct"] is True

            stats = client.get("/api/review/stats")
            assert stats.status_code == 200
            assert stats.json()["active"] >= 1
    finally:
        with SessionLocal() as db:
            db.execute(delete(ReviewItem).where(ReviewItem.course == prefix))
            db.execute(delete(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id))
            db.execute(delete(Quiz).where(Quiz.id == quiz_id))
            db.commit()


def test_manual_review_item_is_recall_and_self_checks() -> None:
    prefix = f"W6手录-{uuid.uuid4().hex[:6]}"
    _cleanup(prefix)
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/review/items",
                json={
                    "question": "手写一张最大子段和的复习卡",
                    "answer": "维护以 i 结尾的最大和，遇到负数就重置。",
                    "course": prefix,
                    "chapter": "动态规划",
                    "source": "聊天 · 手动加入",
                },
            )
            assert created.status_code == 201
            body = created.json()
            assert body["kind"] == "recall"
            assert body["created"] is True
            item_id = body["id"]

            duplicate = client.post(
                "/api/review/items",
                json={"question": "手写一张最大子段和的复习卡", "course": prefix},
            )
            assert duplicate.status_code == 201
            assert duplicate.json()["created"] is False
            assert duplicate.json()["id"] == item_id

            rejected = client.post(
                f"/api/review/items/{item_id}/answer", json={"answer": "A"}
            )
            assert rejected.status_code == 400

            checked = client.post(
                f"/api/review/items/{item_id}/self-check", json={"result": "correct"}
            )
            assert checked.status_code == 200
            assert checked.json()["is_correct"] is True
            assert checked.json()["next_review_at"]
    finally:
        _cleanup(prefix)


def test_weekly_event_infers_weekday_and_expands() -> None:
    prefix = f"W6日程-{uuid.uuid4().hex[:6]}"
    _cleanup(prefix)
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)

    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/calendar/events",
                json={
                    "title": f"{prefix} 算法课",
                    "location": "教三-201",
                    "start_at": start.isoformat(),
                    "recurrence": "weekly",
                },
            )
            assert created.status_code == 201
            body = created.json()
            assert body["weekday"] is not None
            assert body["next_at"]

            listed = client.get("/api/calendar/events", params={"days": 21})
            assert listed.status_code == 200
            occurrences = [x for x in listed.json() if x["title"].startswith(prefix)]
            assert len(occurrences) >= 2

            deleted = client.delete(f"/api/calendar/events/{body['id']}")
            assert deleted.status_code == 200
    finally:
        _cleanup(prefix)


def test_ics_weekly_parse() -> None:
    text = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:算法实验
LOCATION:实验楼 302
DTSTART:20261110T100000
DTEND:20261110T114000
RRULE:FREQ=WEEKLY;BYDAY=MO
END:VEVENT
END:VCALENDAR
"""
    events = parse_ics(text)
    assert len(events) == 1
    assert events[0]["title"] == "算法实验"
    assert events[0]["recurrence"] == "weekly"
    assert events[0]["weekday"] == 0


def test_timetable_image_import_creates_weekly_events(monkeypatch) -> None:
    prefix = f"W6课表-{uuid.uuid4().hex[:6]}"
    _cleanup(prefix)

    async def fake_extract(_path):
        return [
            {
                "title": f"{prefix} 算法课",
                "weekday": 2,
                "start_time": "10:00",
                "end_time": "11:40",
                "location": "教三-201",
            }
        ]

    import app.api.calendar as calendar_api

    monkeypatch.setattr(calendar_api, "extract_timetable", fake_extract)
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/calendar/import-image",
                files={"file": ("timetable.png", b"fake-image", "image/png")},
            )
            assert created.status_code == 201
            body = created.json()
            assert body["imported"] == 1
            assert body["events"][0]["title"] == f"{prefix} 算法课"
            assert body["events"][0]["recurrence"] == "weekly"
            assert body["events"][0]["weekday"] == 1

            listed = client.get("/api/calendar/events", params={"days": 21})
            assert any(item["title"] == f"{prefix} 算法课" for item in listed.json())

            duplicate = client.post(
                "/api/calendar/import-image",
                files={"file": ("timetable.png", b"fake-image", "image/png")},
            )
            assert duplicate.status_code == 400
            assert "没有可导入的新课程" in duplicate.json()["detail"]
    finally:
        _cleanup(prefix)


def test_timetable_image_rejects_wrong_type() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/calendar/import-image",
            files={"file": ("timetable.txt", b"not-an-image", "text/plain")},
        )
        assert response.status_code == 400
        assert "JPG/PNG/WebP" in response.json()["detail"]


def test_habit_toggle_and_streak() -> None:
    prefix = f"W6习惯-{uuid.uuid4().hex[:6]}"
    _cleanup(prefix)

    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/habits", json={"name": f"{prefix} 喝水", "icon": "💧"}
            )
            assert created.status_code == 201
            habit_id = created.json()["id"]

            toggled = client.post(f"/api/habits/{habit_id}/toggle")
            assert toggled.status_code == 200
            assert toggled.json()["done_today"] is True
            assert toggled.json()["streak"] == 1

            listed = client.get("/api/habits")
            assert listed.status_code == 200
            assert any(x["id"] == habit_id for x in listed.json())

            removed = client.delete(f"/api/habits/{habit_id}")
            assert removed.status_code == 200
    finally:
        _cleanup(prefix)


def test_settings_and_usage() -> None:
    user_id = _user_id()
    with SessionLocal() as db:
        record_usage(db, user_id, 1200, 300)
        db.commit()

    with TestClient(app) as client:
        updated = client.put(
            "/api/settings",
            json={
                "morning_enabled": True,
                "morning_time": "07:45",
                "evening_enabled": True,
                "evening_time": "21:45",
                "news_topics": "算法, AI",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["morning_time"] == "07:45"

        summary = client.get("/api/usage/summary", params={"days": 7})
        assert summary.status_code == 200
        body = summary.json()
        assert body["total_turns"] >= 1
        assert body["total_input_tokens"] >= 1200

        # 恢复默认，避免影响其他测试/演示。
        client.put(
            "/api/settings",
            json={
                "morning_enabled": False,
                "morning_time": "07:30",
                "evening_enabled": False,
                "evening_time": "21:30",
                "news_topics": "",
            },
        )


def test_search_notes_returns_structured_citations() -> None:
    prefix = f"W6引用-{uuid.uuid4().hex[:6]}"
    user_id = _user_id()
    text = "费曼学习法要求用自己的话解释概念，发现卡壳就回到原材料。"
    with SessionLocal() as db:
        doc = Document(
            user_id=user_id,
            course=prefix,
            filename="费曼技巧.md",
            status="ready",
        )
        db.add(doc)
        db.flush()
        db.add(
            Chunk(
                user_id=user_id,
                document_id=doc.id,
                course=prefix,
                filename=doc.filename,
                location="第 1 段",
                ordinal=0,
                text=text,
                tokens=" ".join(tokenize(text)),
                token_count=len(tokenize(text)),
            )
        )
        db.commit()
        doc_id = doc.id

    try:
        result = asyncio.run(
            execute_tool_full(
                "search_notes",
                json.dumps({"query": "费曼学习法", "course": prefix}),
                user_id,
            )
        )
        assert "[L1]" in result.text
        assert result.citations
        assert result.citations[0]["document_id"] == doc_id
        assert result.citations[0]["label"] == "L1"
    finally:
        with SessionLocal() as db:
            db.execute(delete(Chunk).where(Chunk.document_id == doc_id))
            db.execute(delete(Document).where(Document.id == doc_id))
            db.commit()


def test_feynman_prompt_overrides_teaching_stage() -> None:
    prompt = build_system_prompt(
        mode="study",
        course="算法设计与分析",
        teaching_stage="answer",
        feynman=True,
    )
    assert "费曼" in prompt
    assert "不主动讲答案" in prompt


def test_past_one_time_event_is_not_reminded(monkeypatch) -> None:
    prefix = f"W6过期日程-{uuid.uuid4().hex[:6]}"
    user_id = _user_id()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with SessionLocal() as db:
        event = CalendarEvent(
            user_id=user_id,
            title=f"{prefix} 已结束",
            start_at=now - timedelta(hours=2),
            recurrence="none",
        )
        db.add(event)
        db.commit()
        event_id = event.id

    sent: list[str] = []

    async def fake_send(*args, **kwargs):  # noqa: ANN002, ANN003
        sent.append(str(args[3]) if len(args) > 3 else "")

    monkeypatch.setattr("app.services.reminders.send_to_user", fake_send)
    try:
        asyncio.run(scan_due_events(now))
        assert all(prefix not in item for item in sent)
    finally:
        with SessionLocal() as db:
            db.execute(delete(CalendarEvent).where(CalendarEvent.id == event_id))
            db.commit()


