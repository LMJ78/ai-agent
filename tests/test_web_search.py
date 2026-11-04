"""联网检索工具测试：不花真钱，用 MockTransport 模拟 Tavily。"""

import asyncio
import json

import httpx
import pytest

from app.agent.prompts import build_system_prompt
from app.config import settings
from app.tools import TOOLS
from app.tools import web_search as web_module
from app.tools.base import ToolError
from app.tools.web_search import WebSearchTool, search_web


def _run(coro):
    return asyncio.run(coro)


def test_web_search_is_registered() -> None:
    assert "web_search" in TOOLS
    assert TOOLS["web_search"].spec()["function"]["name"] == "web_search"


def test_web_search_without_key_is_readable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "")

    with pytest.raises(ToolError, match="TAVILY_API_KEY"):
        _run(search_web("0-1 背包"))


def test_web_search_sends_bearer_and_parses_results(monkeypatch) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test-key")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "动态规划入门",
                        "url": "https://example.com/dp",
                        "content": "0-1 背包的状态转移方程……",
                    }
                ]
            },
        )

    async def go():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await search_web("0-1 背包", 3, client=client)

    results = _run(go())

    assert seen["auth"] == "Bearer tvly-test-key"
    assert str(seen["url"]).endswith("/search")
    assert seen["body"]["query"] == "0-1 背包"
    assert seen["body"]["max_results"] == 3
    assert results[0]["title"] == "动态规划入门"


def test_web_search_401_gives_actionable_error(monkeypatch) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-bad-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": {"error": "unauthorized"}})

    async def go():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await search_web("测试", client=client)

    with pytest.raises(ToolError, match="Key 无效"):
        _run(go())


def test_web_search_tool_formats_citations(monkeypatch) -> None:
    async def fake_search(query: str, max_results: int = 5):
        assert query == "动态规划"
        return [
            {
                "title": "动态规划 - 维基百科",
                "url": "https://example.com/wiki",
                "content": "动态规划是一种\n把问题拆成子问题的方法。",
            }
        ]

    monkeypatch.setattr(web_module, "search_web", fake_search)
    text = _run(WebSearchTool().run(1, {"query": "动态规划"}))

    assert "[W1] 动态规划 - 维基百科" in text
    assert "https://example.com/wiki" in text
    assert "把问题拆成子问题" in text


def test_tool_prompt_mentions_web_citations() -> None:
    prompt = build_system_prompt("study", course="算法设计与分析")
    assert "web_search" in prompt
    assert "[W1]" in prompt
