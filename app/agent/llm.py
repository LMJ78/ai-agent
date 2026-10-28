"""模型客户端。

DeepSeek 兼容 OpenAI 接口，所以直接复用 openai 官方 SDK，只改 base_url。
"""

from functools import lru_cache

from openai import AsyncOpenAI

from app.config import settings


class LLMNotConfiguredError(RuntimeError):
    """没填 API Key 时抛出，接口层转成 503，而不是 500 堆栈。"""


@lru_cache
def get_client() -> AsyncOpenAI:
    key = settings.deepseek_api_key.strip()
    if not key or key.startswith("sk-xxx"):
        raise LLMNotConfiguredError(
            "还没有配置 DEEPSEEK_API_KEY：复制 .env.example 为 .env，填入真实 Key 后重启。"
        )

    return AsyncOpenAI(
        api_key=key,
        base_url=settings.deepseek_base_url,
        timeout=60.0,
        max_retries=1,
    )
