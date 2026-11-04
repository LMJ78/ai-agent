"""联网检索工具：本地课件没覆盖时，让 Agent 查公开网页。

用 Tavily 的 Search API（https://docs.tavily.com）。没有配置 Key 时不会崩，
只会返回一段「未配置」文字，模型可以据此告诉用户先补 Key。
"""

from typing import Any

import httpx

from app.config import settings
from app.tools.base import BaseTool, ToolError


def _clamp_results(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = settings.web_search_max_results
    return max(1, min(number, 8))


async def search_web(
    query: str,
    max_results: int = 5,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """调用 Tavily，返回原始结果列表。

    client 参数只用于测试注入 MockTransport；正常调用不传。
    """
    key = settings.tavily_api_key.strip()
    if not key or key.startswith("tvly-xxx"):
        raise ToolError(
            "还没有配置 TAVILY_API_KEY：在 .env 里填入 Tavily 的 Key 后重启。"
            "本地课件检索 search_notes 不受影响。"
        )

    payload = {
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }
    headers = {"Authorization": f"Bearer {key}"}
    url = f"{settings.tavily_base_url.rstrip('/')}/search"

    async def _post(http: httpx.AsyncClient) -> dict[str, Any]:
        response = await http.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ToolError("联网检索返回了无法解析的内容")
        return data

    try:
        if client is not None:
            data = await _post(client)
        else:
            async with httpx.AsyncClient(timeout=20.0) as http:
                data = await _post(http)
    except httpx.TimeoutException as exc:
        raise ToolError("联网检索超时了，请稍后再试") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            raise ToolError("Tavily Key 无效或没有权限，请检查 .env 里的 TAVILY_API_KEY") from exc
        if status == 429:
            raise ToolError("联网检索太频繁或额度用完了，请稍后再试") from exc
        raise ToolError(f"联网检索失败（HTTP {status}），请稍后再试") from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"联网检索失败：{exc}") from exc

    results = data.get("results")
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)][:max_results]


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "联网搜索公开网页。当本地课程资料 search_notes 没有覆盖、"
        "问题涉及最新信息或网上资料，或者用户明确要求联网时使用。"
        "先查本地资料，本地能回答就不要联网。"
        "回答时用 [W1]、[W2] 标注网页来源，不要编造链接。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索词，尽量具体，例如「0-1 背包 动态规划 状态转移方程」",
            },
            "max_results": {
                "type": "integer",
                "description": "返回几条结果，默认 5，最多 8",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    async def run(self, user_id: int, arguments: dict[str, Any]) -> str:
        # user_id 目前不参与检索；保留参数是为了和别的工具保持同一套协议。
        del user_id
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ToolError("搜索词不能为空")

        results = await search_web(query, _clamp_results(arguments.get("max_results")))
        if not results:
            return "没有搜到相关网页。可以换更具体的关键词，或先查本地课件。"

        blocks = []
        for index, item in enumerate(results, start=1):
            title = str(item.get("title", "")).strip() or "（无标题）"
            url = str(item.get("url", "")).strip()
            content = " ".join(str(item.get("content", "")).split())
            if len(content) > 600:
                content = content[:600] + "…"
            blocks.append(f"[W{index}] {title}\nURL: {url}\n摘要: {content}")

        return (
            "\n\n".join(blocks)
            + "\n\n以上是网页搜索结果，可能不是最新版本；关键结论请点开链接核对。"
        )
