"""待办工具：增 / 查 / 完成 / 删除 / 修改。

所有查询都带 user_id；A 用户永远看不到、也改不了 B 用户的待办。
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Todo
from app.tools.base import BaseTool, ToolError
from app.tools.time import CHINA_TZ


def _parse_due_at(value: Any) -> datetime | None:
    """把模型给的 ISO 时间转成 UTC；只有日期时按当天 23:59。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    try:
        due = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolError("时间格式不对，请用 2026-11-06 23:59 这种格式") from exc

    # 只有日期：补成当天 23:59，符合「周五交报告」的直觉。
    if ":" not in text and len(text) <= 10:
        due = due.replace(hour=23, minute=59)

    if due.tzinfo is None:
        due = due.replace(tzinfo=CHINA_TZ)
    return due.astimezone(timezone.utc)


def _format_due(value: datetime | None) -> str:
    if value is None:
        return "无截止时间"
    # SQLite 取出来可能是 naive，按 UTC 解释。
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(CHINA_TZ).strftime("%m-%d %H:%M")


def _parse_todo_id(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ToolError("todo_id 必须是数字，先用 list 查编号") from exc


class TodoTool(BaseTool):
    name = "todo"
    description = (
        "管理当前用户的待办事项。"
        "action=add 新建（需要 title，可选 due_at）；"
        "action=list 查看（可选 status=pending/done/all）；"
        "action=complete 完成（需要 todo_id）；"
        "action=delete 删除（需要 todo_id）；"
        "action=update 修改标题或截止时间（需要 todo_id）。"
        "用户说「记一下」「提醒我」「我有哪些待办」时使用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "list", "complete", "delete", "update"],
                "description": "要执行的操作",
            },
            "title": {
                "type": "string",
                "description": "待办标题，add / update 时使用",
            },
            "todo_id": {
                "type": "integer",
                "description": "待办编号，complete / delete / update 时使用",
            },
            "due_at": {
                "type": "string",
                "description": "截止时间，ISO 格式，例如 2026-11-06 23:59；只有日期则按 23:59",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "done", "all"],
                "description": "list 时的过滤条件，默认 pending",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    async def run(self, user_id: int, arguments: dict[str, Any]) -> str:
        action = str(arguments.get("action", "")).strip().lower()
        with SessionLocal() as db:
            if action == "add":
                return self._add(db, user_id, arguments)
            if action == "list":
                return self._list(db, user_id, arguments)
            if action in {"complete", "delete", "update"}:
                todo = self._get_own(db, user_id, arguments)
                if action == "complete":
                    todo.done = True
                    db.commit()
                    return f"已完成待办 #{todo.id}：{todo.title}"
                if action == "delete":
                    todo_id, title = todo.id, todo.title
                    db.delete(todo)
                    db.commit()
                    return f"已删除待办 #{todo_id}：{title}"
                return self._update(db, todo, arguments)
            raise ToolError("action 只能是 add / list / complete / delete / update")

    def _add(self, db, user_id: int, arguments: dict[str, Any]) -> str:
        title = str(arguments.get("title", "")).strip()
        if not title:
            raise ToolError("新建待办需要 title")
        todo = Todo(
            user_id=user_id,
            title=title[:255],
            due_at=_parse_due_at(arguments.get("due_at")),
        )
        db.add(todo)
        db.commit()
        db.refresh(todo)
        return f"已添加待办 #{todo.id}：{todo.title}（截止：{_format_due(todo.due_at)}）"

    def _list(self, db, user_id: int, arguments: dict[str, Any]) -> str:
        status = str(arguments.get("status", "pending")).strip().lower()
        if status not in {"pending", "done", "all"}:
            raise ToolError("status 只能是 pending / done / all")

        stmt = select(Todo).where(Todo.user_id == user_id)
        if status == "pending":
            stmt = stmt.where(Todo.done.is_(False))
        elif status == "done":
            stmt = stmt.where(Todo.done.is_(True))

        rows = db.scalars(
            stmt.order_by(Todo.done, Todo.due_at.is_(None), Todo.due_at, Todo.id.desc()).limit(20)
        ).all()
        if not rows:
            return "没有找到符合条件的待办。"

        lines = []
        for todo in rows:
            mark = "✓" if todo.done else "○"
            lines.append(f"{mark} #{todo.id} {todo.title}（截止：{_format_due(todo.due_at)}）")
        return "待办列表：\n" + "\n".join(lines)

    def _get_own(self, db, user_id: int, arguments: dict[str, Any]) -> Todo:
        todo_id = _parse_todo_id(arguments.get("todo_id"))
        todo = db.scalar(select(Todo).where(Todo.id == todo_id, Todo.user_id == user_id))
        if todo is None:
            raise ToolError(f"没有找到 #{todo_id} 这条待办（只能操作自己的待办）")
        return todo

    def _update(self, db, todo: Todo, arguments: dict[str, Any]) -> str:
        changed = False
        if "title" in arguments:
            title = str(arguments.get("title", "")).strip()
            if not title:
                raise ToolError("标题不能为空")
            todo.title = title[:255]
            changed = True
        if "due_at" in arguments:
            todo.due_at = _parse_due_at(arguments.get("due_at"))
            changed = True
        if not changed:
            raise ToolError("update 至少需要 title 或 due_at")

        db.commit()
        return f"已更新待办 #{todo.id}：{todo.title}（截止：{_format_due(todo.due_at)}）"
