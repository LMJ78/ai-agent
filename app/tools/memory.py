"""长期记忆工具：记住 / 查看 / 搜索 / 删除。"""

from typing import Any

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Memory
from app.services.memories import (
    add_memory,
    delete_memory,
    format_memory,
    list_memories,
    normalize_kind,
    recall_memories,
)
from app.tools.base import BaseTool, ToolError


class MemoryTool(BaseTool):
    name = "memory"
    description = (
        "管理用户的长期记忆。"
        "action=add 记住一条（需要 content，可选 kind）；"
        "action=list 查看（可选 kind）；"
        "action=search 按关键词找（需要 query）；"
        "action=delete 删除（需要 memory_id）。"
        "用户说「记住」「你记得我什么」「忘了这条」时使用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "list", "search", "delete"],
                "description": "要执行的操作",
            },
            "content": {
                "type": "string",
                "description": "要记住的事实，一句话，add 时使用",
            },
            "kind": {
                "type": "string",
                "enum": ["identity", "preference", "plan", "relationship", "other"],
                "description": "事实类型：身份/偏好/计划/关系/其他",
            },
            "query": {
                "type": "string",
                "description": "搜索关键词，search 时使用",
            },
            "memory_id": {
                "type": "integer",
                "description": "记忆编号，delete 时使用",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    async def run(self, user_id: int, arguments: dict[str, Any]) -> str:
        action = str(arguments.get("action", "")).strip().lower()
        with SessionLocal() as db:
            if action == "add":
                content = str(arguments.get("content", "")).strip()
                if not content:
                    raise ToolError("add 需要 content")
                try:
                    memory, created = add_memory(
                        db, user_id, content, normalize_kind(arguments.get("kind"))
                    )
                except ValueError as exc:
                    raise ToolError(str(exc)) from exc
                if not created:
                    return f"这条已经记过了：{format_memory(memory)}"
                return f"已记住：{format_memory(memory)}"

            if action == "list":
                kind = arguments.get("kind")
                rows = list_memories(db, user_id, kind=kind if kind else None)
                if not rows:
                    return "还没有记住关于你的信息。"
                return "我记住的这些：\n" + "\n".join(
                    f"#{memory.id} {format_memory(memory)}" for memory in rows
                )

            if action == "search":
                query = str(arguments.get("query", "")).strip()
                if not query:
                    raise ToolError("search 需要 query")
                rows = recall_memories(db, user_id, query)
                if not rows:
                    return f"没有找到和「{query}」相关的记忆。"
                return "找到这些相关记忆：\n" + "\n".join(
                    f"#{memory.id} {format_memory(memory)}" for memory in rows
                )

            if action == "delete":
                try:
                    memory_id = int(arguments.get("memory_id"))
                except (TypeError, ValueError) as exc:
                    raise ToolError("memory_id 必须是数字") from exc
                memory = db.scalar(
                    select(Memory).where(
                        Memory.id == memory_id, Memory.user_id == user_id
                    )
                )
                if memory is None:
                    raise ToolError(f"没有找到 #{memory_id}（只能删除自己的记忆）")
                label = format_memory(memory)
                if not delete_memory(db, user_id, memory_id):
                    raise ToolError("删除失败，记忆可能已经不在了")
                return f"已删除：{label}"

            raise ToolError("action 只能是 add / list / search / delete")
