"""手写 Agent 循环。

本质就一句话：
    模型说「要调工具」→ 执行 → 把结果喂回去 → 再问模型，直到它直接回答。

W2 先不做流式工具调用：每一轮用非流式请求拿到 tool_calls，
最后一轮拿到完整回答后，再由接口层按 SSE 分块推给前端。
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.tools import execute_tool_full, get_tool_specs

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


@dataclass
class AgentEvent:
    type: str  # tool_call / tool_result / final / error
    data: dict[str, Any] = field(default_factory=dict)


def _assistant_message(message: Any) -> dict[str, Any]:
    """把 SDK 的 message 转成下一次请求能用的 dict（只保留必要字段）。"""
    tool_calls = []
    for call in message.tool_calls or []:
        tool_calls.append(
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments or "{}",
                },
            }
        )
    return {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": tool_calls,
    }


async def run_agent(
    client: Any,
    messages: list[dict[str, Any]],
    user_id: int,
    max_rounds: int = MAX_TOOL_ROUNDS,
    course: str = "",
) -> AsyncIterator[AgentEvent]:
    """跑完整个「模型 ↔ 工具」循环，按事件 yield 出去。"""
    for round_no in range(1, max_rounds + 1):
        try:
            response = await client.chat.completions.create(
                model=settings.deepseek_model,
                messages=messages,
                tools=get_tool_specs(),
                tool_choice="auto",
                temperature=settings.temperature,
                max_tokens=settings.max_tokens,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Agent 第 %s 轮模型调用失败", round_no)
            yield AgentEvent("error", {"message": f"模型调用失败：{exc}"})
            return

        if not response.choices:
            yield AgentEvent("error", {"message": "模型没有返回任何结果"})
            return

        usage = getattr(response, "usage", None)
        if usage is not None:
            yield AgentEvent(
                "usage",
                {
                    "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                },
            )

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)

        # 没有工具调用 = 模型准备直接回答，循环结束。
        if not tool_calls:
            yield AgentEvent("final", {"content": message.content or ""})
            return

        messages.append(_assistant_message(message))

        for call in tool_calls:
            name = call.function.name
            raw_arguments = call.function.arguments or "{}"
            yield AgentEvent(
                "tool_call",
                {
                    "id": call.id,
                    "name": name,
                    "arguments": raw_arguments,
                    "round": round_no,
                },
            )

            result = await execute_tool_full(
                name, raw_arguments, user_id, default_course=course
            )
            yield AgentEvent(
                "tool_result",
                {
                    "id": call.id,
                    "name": name,
                    "result": result.text[:600],  # 前端只展示摘要，完整结果给模型
                    "citations": result.citations,
                },
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result.text,
                }
            )

    # 到上限还没收敛，主动停，避免死循环和账单失控。
    yield AgentEvent(
        "error",
        {"message": f"工具调用超过 {max_rounds} 轮，我先停在这里。你可以把问题拆小一点再问。"},
    )
