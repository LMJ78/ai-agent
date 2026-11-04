"""工具协议。

每个工具只需要提供四样东西：
- name：模型看到的工具名
- description：什么时候该用它（写给模型看的大白话）
- parameters：JSON Schema，告诉模型参数长什么样
- run()：真正执行，返回一段文本给模型
"""

from abc import ABC, abstractmethod
from typing import Any, ClassVar


class ToolError(Exception):
    """工具执行失败。会被转成一段文本回给模型，而不是让整个请求崩掉。"""


class BaseTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    parameters: ClassVar[dict[str, Any]]

    @abstractmethod
    async def run(self, user_id: int, arguments: dict[str, Any]) -> str:
        """执行工具。user_id 用来做数据隔离，工具内部必须自己按它过滤。"""

    def spec(self) -> dict[str, Any]:
        """转成 OpenAI / DeepSeek 的 tools 格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
