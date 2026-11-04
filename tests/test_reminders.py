"""待办提醒扫描：成功、去重、失败重试、没有通道时跳过。"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.init import init_db
from app.db.models import PushChannel, Todo, User
from app.services import reminders
from app.services.push import PushError, PushNotConfiguredError

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)


def _demo_user_id() -> int:
    init_db()
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.username == "demo"))
    assert user_id is not None
    return user_id


def _cleanup(user_id: int, title_prefix: str) -> None:
    with SessionLocal() as db:
        db.execute(delete(Todo).where(Todo.user_id == user_id, Todo.title.like(f"{title_prefix}%")))
        db.execute(delete(PushChannel).where(PushChannel.user_id == user_id))
        db.commit()


def test_scan_sends_once_and_marks_reminded(monkeypatch) -> None:
    user_id = _demo_user_id()
    prefix = f"W4提醒-{uuid.uuid4().hex[:6]}"
    _cleanup(user_id, prefix)

    with SessionLocal() as db:
        db.add(PushChannel(user_id=user_id, provider="pushplus", token="test-token", enabled=True))
        todo = Todo(
            user_id=user_id,
            title=f"{prefix} 交实验报告",
            due_at=NOW - timedelta(minutes=10),
        )
        db.add(todo)
        db.commit()
        todo_id = todo.id

    sent: list[str] = []

    async def fake_send(db, user_id, title, content):
        sent.append(content)
        return {"code": 200}

    monkeypatch.setattr(reminders, "send_to_user", fake_send)

    try:
        first = asyncio.run(reminders.scan_due_todos(now=NOW))
        assert first["sent"] == 1
        assert first["due"] == 1

        with SessionLocal() as db:
            todo = db.get(Todo, todo_id)
            assert todo is not None and todo.reminded_at is not None

        second = asyncio.run(reminders.scan_due_todos(now=NOW))
        assert second["sent"] == 0
        assert len(sent) == 1
    finally:
        _cleanup(user_id, prefix)


def test_scan_skips_without_channel_then_sends_after_config(monkeypatch) -> None:
    user_id = _demo_user_id()
    prefix = f"W4无通道-{uuid.uuid4().hex[:6]}"
    _cleanup(user_id, prefix)

    with SessionLocal() as db:
        todo = Todo(
            user_id=user_id,
            title=f"{prefix} 买资料",
            due_at=NOW - timedelta(minutes=1),
        )
        db.add(todo)
        db.commit()
        todo_id = todo.id

    sent: list[str] = []

    async def fake_send(db, user_id, title, content):
        sent.append(content)
        return {"code": 200}

    try:
        # 第一次没有通道：真实 send_to_user 会抛 PushNotConfiguredError，不消耗重试次数。
        first = asyncio.run(reminders.scan_due_todos(now=NOW))
        assert first["skipped"] == 1
        assert first["sent"] == 0

        with SessionLocal() as db:
            todo = db.get(Todo, todo_id)
            assert todo.remind_attempts == 0
            assert todo.reminded_at is None
            db.add(PushChannel(user_id=user_id, provider="pushplus", token="test-token"))
            db.commit()

        monkeypatch.setattr(reminders, "send_to_user", fake_send)
        second = asyncio.run(reminders.scan_due_todos(now=NOW))
        assert second["sent"] == 1
    finally:
        _cleanup(user_id, prefix)


def test_scan_retries_three_times_then_stops(monkeypatch) -> None:
    user_id = _demo_user_id()
    prefix = f"W4重试-{uuid.uuid4().hex[:6]}"
    _cleanup(user_id, prefix)

    with SessionLocal() as db:
        db.add(PushChannel(user_id=user_id, provider="pushplus", token="test-token"))
        todo = Todo(
            user_id=user_id,
            title=f"{prefix} 交作业",
            due_at=NOW - timedelta(minutes=1),
        )
        db.add(todo)
        db.commit()
        todo_id = todo.id

    async def fail_send(db, user_id, title, content):
        raise PushError("模拟 PushPlus 失败")

    monkeypatch.setattr(reminders, "send_to_user", fail_send)

    try:
        for expected in (1, 2, 3):
            result = asyncio.run(reminders.scan_due_todos(now=NOW))
            assert result["failed"] == 1
            with SessionLocal() as db:
                assert db.get(Todo, todo_id).remind_attempts == expected

        after = asyncio.run(reminders.scan_due_todos(now=NOW))
        assert after["due"] == 0
    finally:
        _cleanup(user_id, prefix)
