"""长期记忆：API CRUD、搜索、用户隔离、工具去重。"""

import asyncio
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import settings
from app.db.base import SessionLocal
from app.db.init import init_db
from app.db.models import Memory, User
from app.main import app
from app.services.memories import remember_explicit
from app.tools.memory import MemoryTool


def _demo_user_id() -> int:
    init_db()
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.username == "demo"))
    assert user_id is not None
    return user_id


def test_memory_api_crud_and_search(monkeypatch) -> None:
    monkeypatch.setattr(settings, "reminder_worker_enabled", False)
    user_id = _demo_user_id()
    content = f"我不吃香菜-{uuid.uuid4().hex[:6]}"

    with TestClient(app) as client:
        created = client.post(
            "/api/memories", json={"content": content, "kind": "preference"}
        )
        assert created.status_code == 200
        memory_id = created.json()["id"]

        listed = client.get("/api/memories").json()
        assert any(item["id"] == memory_id for item in listed)

        found = client.get("/api/memories", params={"q": "香菜"}).json()
        assert any(item["id"] == memory_id for item in found)

        removed = client.delete(f"/api/memories/{memory_id}")
        assert removed.status_code == 200
        assert all(item["id"] != memory_id for item in client.get("/api/memories").json())

    with SessionLocal() as db:
        db.execute(delete(Memory).where(Memory.user_id == user_id, Memory.content == content))
        db.commit()


def test_memory_is_isolated(monkeypatch) -> None:
    monkeypatch.setattr(settings, "reminder_worker_enabled", False)
    _demo_user_id()
    suffix = uuid.uuid4().hex[:6]

    with SessionLocal() as db:
        other = User(username=f"other-{suffix}", display_name="另一个同学")
        db.add(other)
        db.commit()
        db.refresh(other)
        memory = Memory(user_id=other.id, kind="preference", content=f"别的用户的记忆-{suffix}")
        db.add(memory)
        db.commit()
        other_memory_id = memory.id

    try:
        with TestClient(app) as client:
            listed = client.get("/api/memories").json()
            assert all(item["id"] != other_memory_id for item in listed)
            assert client.delete(f"/api/memories/{other_memory_id}").status_code == 404
    finally:
        with SessionLocal() as db:
            db.execute(delete(Memory).where(Memory.user_id == other.id))
            db.execute(delete(User).where(User.id == other.id))
            db.commit()


def test_memory_tool_add_dedupes_and_deletes() -> None:
    user_id = _demo_user_id()
    content = f"我喜欢在晚上学习-{uuid.uuid4().hex[:6]}"
    tool = MemoryTool()

    try:
        first = asyncio.run(
            tool.run(user_id, {"action": "add", "content": content, "kind": "preference"})
        )
        assert "已记住" in first

        second = asyncio.run(tool.run(user_id, {"action": "add", "content": content}))
        assert "已经记过" in second

        found = asyncio.run(tool.run(user_id, {"action": "search", "query": "晚上学习"}))
        assert content in found

        with SessionLocal() as db:
            memory_id = db.scalar(
                select(Memory.id).where(Memory.user_id == user_id, Memory.content == content)
            )
        assert memory_id is not None

        removed = asyncio.run(tool.run(user_id, {"action": "delete", "memory_id": memory_id}))
        assert "已删除" in removed
    finally:
        with SessionLocal() as db:
            db.execute(delete(Memory).where(Memory.user_id == user_id, Memory.content == content))
            db.commit()


def test_remember_explicit_extracts_kind() -> None:
    user_id = _demo_user_id()
    content = f"我不吃香菜-{uuid.uuid4().hex[:6]}"
    with SessionLocal() as db:
        memory = remember_explicit(db, user_id, f"记住{content}")
        assert memory is not None
        assert memory.content == content
        assert memory.kind == "preference"
        memory_id = memory.id

    try:
        with SessionLocal() as db:
            assert db.get(Memory, memory_id) is not None
    finally:
        with SessionLocal() as db:
            db.execute(delete(Memory).where(Memory.id == memory_id))
            db.commit()
