"""Agent 循环测试：验证「模型 → 工具 → 模型」真的转起来了。"""

import asyncio
from types import SimpleNamespace

from app.agent.loop import run_agent


def _tool_call(name: str, arguments: str, call_id: str = "call_1") -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _response(content: str | None = None, tool_calls=None) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)

    async def create(self, **_kwargs):
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


async def _collect(events):
    return [event async for event in events]


def test_agent_executes_tool_then_answers() -> None:
    client = FakeClient(
        [
            _response(tool_calls=[_tool_call("calculator", '{"expression": "2+3*4"}')]),
            _response(content="结果是 14。"),
        ]
    )
    messages = [{"role": "user", "content": "2+3*4 等于多少？"}]

    events = asyncio.run(_collect(run_agent(client, messages, user_id=1)))

    assert [event.type for event in events] == ["tool_call", "tool_result", "final"]
    assert "14" in events[1].data["result"]
    assert events[2].data["content"] == "结果是 14。"
    # 工具结果已经回填进 messages，模型第二次调用能看到。
    assert messages[-1]["role"] == "tool"
    assert "14" in messages[-1]["content"]


def test_agent_stops_after_max_rounds() -> None:
    # 每次都要求调工具，模拟模型不肯收敛。
    responses = [
        _response(tool_calls=[_tool_call("get_current_time", "{}")]) for _ in range(3)
    ]
    client = FakeClient(responses)
    messages = [{"role": "user", "content": "一直查时间"}]

    events = asyncio.run(_collect(run_agent(client, messages, user_id=1, max_rounds=2)))

    assert events[-1].type == "error"
    assert "超过 2 轮" in events[-1].data["message"]
