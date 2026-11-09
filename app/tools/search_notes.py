"""课程资料检索工具：让 Agent 先查课件，再回答。"""

from typing import Any

from app.rag.retriever import search_chunks
from app.tools.base import BaseTool, ToolError, ToolResult


class SearchNotesTool(BaseTool):
    name = "search_notes"
    description = (
        "检索当前用户上传的课程资料（课件/讲义）。"
        "当用户问课程概念、原理、算法、复习内容，或者问题可能和课件有关时，"
        "先调用它，再根据返回的片段回答；回答里用 [L1]、[L2] 标注出处。"
        "资料里没有就直说，不要编造。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索关键词或问题，尽量保留课程术语",
            },
            "course": {
                "type": "string",
                "description": "课程名，例如「算法设计与分析」；不确定就留空",
            },
            "top_k": {
                "type": "integer",
                "description": "返回几个片段，默认 4，最多 8",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    async def run(self, user_id: int, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ToolError("检索词不能为空")

        course = str(arguments.get("course", "")).strip() or None
        try:
            top_k = int(arguments.get("top_k", 4))
        except (TypeError, ValueError):
            top_k = 4
        top_k = max(1, min(top_k, 8))

        results = search_chunks(user_id=user_id, query=query, course=course, top_k=top_k)
        if not results:
            return ToolResult(
                "没有检索到相关课程资料。可能还没上传课件，或者这门课的资料里没有相关内容。"
            )

        blocks = []
        citations = []
        for index, item in enumerate(results, start=1):
            blocks.append(
                f"[L{index}] {item.filename} / {item.location}\n{item.text}"
            )
            citations.append(
                {
                    "type": "note",
                    "label": f"L{index}",
                    "document_id": item.document_id,
                    "filename": item.filename,
                    "location": item.location,
                    "course": item.course,
                    "chapter": item.chapter,
                    "snippet": item.text[:500],
                }
            )
        return ToolResult("\n\n".join(blocks), citations)
