"""工具注册表：把工具收在一起，并提供给模型用的 schema。"""

import json
import logging
from typing import Any

from app.tools.base import BaseTool, ToolError, ToolResult
from app.tools.calculator import CalculatorTool
from app.tools.memory import MemoryTool
from app.tools.search_notes import SearchNotesTool
from app.tools.time import TimeTool
from app.tools.todo import TodoTool
from app.tools.web_search import WebSearchTool

logger = logging.getLogger(__name__)

_TOOL_LIST: list[BaseTool] = [
    TimeTool(),
    CalculatorTool(),
    TodoTool(),
    MemoryTool(),
    SearchNotesTool(),
    WebSearchTool(),
]
TOOLS: dict[str, BaseTool] = {tool.name: tool for tool in _TOOL_LIST}


def get_tool_specs() -> list[dict[str, Any]]:
    return [tool.spec() for tool in _TOOL_LIST]


async def execute_tool_full(
    name: str,
    raw_arguments: str | None,
    user_id: int,
    default_course: str = "",
) -> ToolResult:
    """执行工具；文本给模型，citations 给前端。失败也返回文本。"""
    tool = TOOLS.get(name)
    if tool is None:
        return ToolResult(f"工具执行失败：没有名为 {name} 的工具")

    try:
        arguments = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError:
        return ToolResult("工具执行失败：参数不是合法 JSON")

    if not isinstance(arguments, dict):
        return ToolResult("工具执行失败：参数必须是 JSON 对象")

    # 会话已经选了科目时，检索默认只查这门课；模型显式传 course 则以它为准。
    if default_course and name == "search_notes" and not arguments.get("course"):
        arguments["course"] = default_course

    try:
        result = await tool.run(user_id, arguments)
        if isinstance(result, ToolResult):
            return ToolResult(result.text[:4000], result.citations)
        return ToolResult(str(result)[:4000])
    except ToolError as exc:
        return ToolResult(f"工具执行失败：{exc}")
    except Exception:
        logger.exception("工具 %s 执行异常", name)
        return ToolResult("工具执行失败：内部错误，请换个方式再试")


async def execute_tool(
    name: str,
    raw_arguments: str | None,
    user_id: int,
    default_course: str = "",
) -> str:
    """兼容旧调用：只拿文本。"""
    result = await execute_tool_full(name, raw_arguments, user_id, default_course)
    return result.text
