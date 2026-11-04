"""W3 拍照/联网自检。

用法（在 ai-agent 目录下）：
    python scripts/check_w3_extras.py
    python scripts/check_w3_extras.py --image data/sample_question.jpg
    python scripts/check_w3_extras.py --web "0-1 背包 状态转移方程"

这个脚本只做两件事：检查 Key 有没有配、在配置了的情况下真实调用一次。
它不会把 Key 打印出来。
"""

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agent.vision import VisionError, VisionNotConfiguredError, transcribe_image  # noqa: E402
from app.config import settings  # noqa: E402
from app.tools.base import ToolError  # noqa: E402
from app.tools.web_search import WebSearchTool  # noqa: E402


def _key_status(value: str) -> str:
    return "已配置" if value.strip() and not value.startswith(("sk-xxx", "tvly-xxx")) else "未配置"


async def _check_image(path: Path) -> int:
    print(f"\n[拍照] VISION_API_KEY={_key_status(settings.vision_api_key)}，模型={settings.vision_model}")
    if _key_status(settings.vision_api_key) == "未配置":
        print("跳过真实调用：先在 .env 填 VISION_API_KEY，再重启/重跑。")
        return 1
    try:
        text = await transcribe_image(path)
    except (VisionNotConfiguredError, VisionError) as exc:
        print(f"失败：{exc}")
        return 1
    print("转写结果：")
    print(text)
    return 0


async def _check_web(query: str) -> int:
    print(f"\n[联网] TAVILY_API_KEY={_key_status(settings.tavily_api_key)}")
    if _key_status(settings.tavily_api_key) == "未配置":
        print("跳过真实调用：先在 .env 填 TAVILY_API_KEY，再重启/重跑。")
        return 1
    try:
        text = await WebSearchTool().run(0, {"query": query, "max_results": 3})
    except ToolError as exc:
        print(f"失败：{exc}")
        return 1
    print(text)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="W3 拍照/联网自检")
    parser.add_argument("--image", type=Path, help="一张印刷体题目图片")
    parser.add_argument("--web", type=str, help="联网搜索词")
    args = parser.parse_args()

    print("W3 扩展能力自检")
    print(f"  VISION_API_KEY：{_key_status(settings.vision_api_key)}")
    print(f"  TAVILY_API_KEY：{_key_status(settings.tavily_api_key)}")

    if not args.image and not args.web:
        print("\n没有指定 --image / --web，只检查了 Key 状态。")
        return 0

    failures = 0
    if args.image:
        if not args.image.exists():
            print(f"\n图片不存在：{args.image}")
            failures += 1
        else:
            failures += asyncio.run(_check_image(args.image))
    if args.web:
        failures += asyncio.run(_check_web(args.web))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
