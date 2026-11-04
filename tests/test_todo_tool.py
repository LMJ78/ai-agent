"""待办工具测试：CRUD + 用户隔离。"""

import asyncio
import re
import uuid

from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.init import init_db
from app.db.models import Todo, User
from app.tools.todo import TodoTool


def _demo_user_id() -> int:
    init_db()
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.username == "demo"))
    assert user_id is not None
    return user_id


def test_todo_crud_and_isolation() -> None:
    user_id = _demo_user_id()
    title = f"W2测试-{uuid.uuid4().hex[:8]}"
    tool = TodoTool()

    try:
        added = asyncio.run(
            tool.run(user_id, {"action": "add", "title": title, "due_at": "2026-11-06"})
        )
        assert title in added
        assert "11-06 23:59" in added  # 只有日期时补成 23:59
        todo_id = int(re.search(r"#(\d+)", added).group(1))

        with SessionLocal() as db:
            todo = db.get(Todo, todo_id)
            assert todo is not None and todo.due_at is not None

        listed = asyncio.run(tool.run(user_id, {"action": "list", "status": "pending"}))
        assert title in listed

        updated = asyncio.run(
            tool.run(
                user_id,
                {"action": "update", "todo_id": todo_id, "title": title + "-改"},
            )
        )
        assert "已更新" in updated

        completed = asyncio.run(tool.run(user_id, {"action": "complete", "todo_id": todo_id}))
        assert "已完成" in completed
        with SessionLocal() as db:
            assert db.get(Todo, todo_id).done is True

        # 另一个用户看不到这条待办
        other = asyncio.run(tool.run(user_id + 999, {"action": "list", "status": "all"}))
        assert title not in other

        deleted = asyncio.run(tool.run(user_id, {"action": "delete", "todo_id": todo_id}))
        assert "已删除" in deleted
        with SessionLocal() as db:
            assert db.get(Todo, todo_id) is None
    finally:
        with SessionLocal() as db:
            db.execute(delete(Todo).where(Todo.title.like(f"{title}%")))
            db.commit()
