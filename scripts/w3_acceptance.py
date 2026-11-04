"""W3 验收小工具：10 张题目截图 + 6 个问题。

用法（先启动 uvicorn，在 ai-agent 目录下）：
    python scripts/w3_acceptance.py
    python scripts/w3_acceptance.py --skip-images
    python scripts/w3_acceptance.py --skip-chat

它会：
1. 生成 10 张「印刷体题目截图」（白底黑字，不是手机实拍）；
2. 逐张调 /api/questions/upload，检查 OCR 是否可读；
3. 用 6 个问题调 /api/chat，检查本地 [L]、联网 [W] 和「不知道」；
4. 把结果写到 data/acceptance/w3_report.md。

注意：会真实调用 Qwen-VL 和 DeepSeek，产生少量费用；不打印任何 Key。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "http://127.0.0.1:8000"
COURSE = "算法设计与分析"
IMAGE_DIR = ROOT / "data" / "acceptance" / "images"
REPORT_PATH = ROOT / "data" / "acceptance" / "w3_report.md"
FONT_REGULAR = Path(r"C:\Windows\Fonts\msyh.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")

# 每张图只放一道题，题干保持短，方便 OCR 和人工核对。
PRINT_CASES = [
    {
        "key": "q01",
        "body": "一个算法中有两层嵌套循环，外层和内层都执行 n 次，\n每次循环内是常数时间操作。\n请写出该算法的时间复杂度。",
        "expect": ["时间复杂度", "O(n^2)"],
    },
    {
        "key": "q02",
        "body": "递归式 T(n) = 2T(n/2) + n，其中 T(1) = 1。\n请用大 O 记号表示 T(n)。",
        "expect": ["T(n)", "n/2"],
    },
    {
        "key": "q03",
        "body": "0-1 背包问题中，dp[i][j] 表示前 i 个物品、容量 j 的最大价值。\n请写出状态转移方程。",
        "expect": ["dp", "max", "w[i]"],
    },
    {
        "key": "q04",
        "body": "分治算法通常分为哪三个步骤？\n请按顺序写出这三个步骤。",
        "expect": ["分治", "步骤"],
    },
    {
        "key": "q05",
        "body": "快速排序的平均时间复杂度和最坏时间复杂度分别是多少？\n请分别写出。",
        "expect": ["快速排序", "时间复杂度"],
    },
    {
        "key": "q06",
        "body": "Dijkstra 算法为什么不能处理带负权边的图？\n请用一句话说明原因。",
        "expect": ["负权", "不能"],
    },
    {
        "key": "q07",
        "body": "二分查找要求数组满足什么条件？\n它的时间复杂度是多少？",
        "expect": ["二分查找", "时间复杂度"],
    },
    {
        "key": "q08",
        "body": "最小生成树常用的两种算法是 Prim 和 Kruskal。\n请分别写出它们的主要适用场景。",
        "expect": ["Prim", "Kruskal"],
    },
    {
        "key": "q09",
        "body": "最长公共子序列（LCS）中，当两个字符相等时，\n状态转移方程是什么？",
        "expect": ["dp", "相等"],
    },
    {
        "key": "q10",
        "body": "动态规划适合解决什么样的问题？\n请写出两个关键性质。",
        "expect": ["动态规划", "性质"],
    },
]

CHAT_CASES = [
    {
        "key": "local_time",
        "kind": "local",
        "message": "请先查课件再回答：算法的时间复杂度是什么？",
        "course": COURSE,
        "expect": ["增长", "O("],
    },
    {
        "key": "local_divide",
        "kind": "local",
        "message": "分治法的基本思想是什么？请按步骤说明。",
        "course": COURSE,
        "expect": ["分解", "合并"],
    },
    {
        "key": "local_dp",
        "kind": "local",
        "message": "动态规划的基本思想是什么？关键性质有哪些？",
        "course": COURSE,
        "expect": ["最优子结构", "重叠子问题"],
    },
    {
        "key": "local_knapsack",
        "kind": "local",
        "message": "0-1 背包的状态转移方程是什么？请解释每个符号。",
        "course": COURSE,
        "expect": ["dp", "max", "w[i]"],
    },
    {
        "key": "web_python314",
        "kind": "web",
        "message": "联网查一下：Python 3.14 有哪些新特性？请列 2 条并给出来源。",
        "course": COURSE,
        "expect": ["Python 3.14"],
    },
    {
        "key": "none_classroom",
        "kind": "none",
        "message": "我明天上午的算法课在哪个教室？",
        "course": COURSE,
        "expect": [],
    },
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_REGULAR
    if not path.exists():
        raise SystemExit(f"找不到中文字体：{path}")
    return ImageFont.truetype(str(path), size=size, index=0)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines():
        current = ""
        for char in paragraph:
            trial = current + char
            if draw.textlength(trial, font=font) <= width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = char
        lines.append(current)
    return lines


def make_images() -> list[Path]:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, case in enumerate(PRINT_CASES, start=1):
        width, height = 1240, 900
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        draw.text((80, 48), "算法设计与分析 · 随堂练习", font=_font(38, bold=True), fill="black")
        draw.line((80, 112, width - 80, 112), fill="black", width=2)
        draw.text((80, 150), f"{index}.", font=_font(32, bold=True), fill="black")
        body_font = _font(31)
        lines = _wrap(draw, case["body"], body_font, 1010)
        y = 150
        for line in lines:
            draw.text((130, y), line, font=body_font, fill="black")
            y += 50
        draw.text(
            (80, height - 82),
            "姓名：________________    学号：________________",
            font=_font(23),
            fill=(90, 90, 90),
        )
        target = IMAGE_DIR / f"{case['key']}.png"
        image.save(target, format="PNG")
        paths.append(target)
    return paths


def _norm(text: str) -> str:
    value = text.lower()
    value = value.replace("²", "^2").replace("³", "^3").replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", "", value)


def _has_any(text: str, needles: list[str]) -> bool:
    haystack = _norm(text)
    return any(_norm(item) in haystack for item in needles)


def _has_citation(text: str, tag: str) -> bool:
    return re.search(rf"\[{tag}\d*\]", text or "") is not None


def _snippet(text: str, limit: int = 130) -> str:
    value = re.sub(r"\s+", " ", (text or "").strip())
    return value[:limit] + ("…" if len(value) > limit else "")


async def upload_image(client: httpx.AsyncClient, path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        files = {"file": (path.name, handle, "image/png")}
        data = {"course": COURSE, "chapter": "综合"}
        response = await client.post(f"{BASE_URL}/api/questions/upload", files=files, data=data)
    response.raise_for_status()
    return response.json()


async def confirm_question(client: httpx.AsyncClient, question_id: int) -> dict[str, Any]:
    response = await client.post(f"{BASE_URL}/api/questions/{question_id}/confirm", json={})
    response.raise_for_status()
    return response.json()


async def ask(client: httpx.AsyncClient, case: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "message": case["message"],
        "mode": "study",
        "course": case.get("course") or COURSE,
    }
    events: list[dict[str, Any]] = []
    async with client.stream("POST", f"{BASE_URL}/api/chat", json=payload) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                break
            if data:
                events.append(json.loads(data))

    final = "".join(str(event.get("delta", "")) for event in events)
    tool_calls = [event for event in events if event.get("type") == "tool_call"]
    errors = [event.get("error", "") for event in events if event.get("error")]
    return {
        "final": final,
        "tool_calls": tool_calls,
        "errors": errors,
        "session_id": next((event.get("session_id") for event in events if event.get("session_id")), None),
    }


def evaluate_chat(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    text = result["final"]
    kind = case["kind"]
    tool_names = [str(call.get("name", "")) for call in result["tool_calls"]]
    if kind == "local":
        passed = _has_any(text, case["expect"]) and _has_citation(text, "L")
    elif kind == "web":
        passed = "web_search" in tool_names and _has_citation(text, "W")
    else:
        passed = any(
            word in text
            for word in (
                "不知道",
                "不确定",
                "不清楚",
                "无法",
                "没办法",
                "没有相关",
                "没有你的",
                "没有课表",
                "查不到",
                "建议你",
            )
        )
    return {
        **result,
        "tool_names": tool_names,
        "passed": passed,
        "citation": "[L]" if _has_citation(text, "L") else ("[W]" if _has_citation(text, "W") else ""),
    }


async def run(do_images: bool, do_chat: bool) -> int:
    if not do_images and not do_chat:
        raise SystemExit("--skip-images 和 --skip-chat 不能同时使用")

    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0)) as client:
        try:
            health = await client.get(f"{BASE_URL}/health")
            health.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"服务没起来：{BASE_URL}/health -> {exc}") from exc

        image_rows: list[dict[str, Any]] = []
        if do_images:
            paths = make_images()
            print(f"已生成 {len(paths)} 张截图：{IMAGE_DIR}")
            for index, (case, path) in enumerate(zip(PRINT_CASES, paths, strict=True), start=1):
                try:
                    question = await upload_image(client, path)
                    await confirm_question(client, question["id"])
                    text = question.get("parsed_text", "")
                    readable = _has_any(text, case["expect"])
                    image_rows.append(
                        {
                            "index": index,
                            "key": case["key"],
                            "path": path,
                            "question_id": question["id"],
                            "readable": readable,
                            "text": text,
                            "error": "",
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    image_rows.append(
                        {
                            "index": index,
                            "key": case["key"],
                            "path": path,
                            "question_id": None,
                            "readable": False,
                            "text": "",
                            "error": str(exc),
                        }
                    )
                row = image_rows[-1]
                print(f"[{index}/10] {case['key']} readable={row['readable']} err={row['error'][:80]}")

        chat_rows: list[dict[str, Any]] = []
        if do_chat:
            for index, case in enumerate(CHAT_CASES, start=1):
                try:
                    raw = await ask(client, case)
                    result = evaluate_chat(case, raw)
                except Exception as exc:  # noqa: BLE001
                    result = {
                        "final": "",
                        "tool_calls": [],
                        "errors": [str(exc)],
                        "session_id": None,
                        "tool_names": [],
                        "passed": False,
                        "citation": "",
                    }
                chat_rows.append({**case, **result})
                print(
                    f"[{index}/6] {case['key']} passed={result['passed']} "
                    f"tools={','.join(result['tool_names']) or '-'} "
                    f"err={'; '.join(result['errors'])[:80]}"
                )

    readable_count = sum(1 for row in image_rows if row["readable"])
    chat_pass_count = sum(1 for row in chat_rows if row["passed"])
    local_citation_count = sum(
        1 for row in chat_rows if row["kind"] == "local" and row["citation"] == "[L]"
    )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# W3 验收报告",
        "",
        f"- 时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 服务：{BASE_URL}",
        f"- 课程：{COURSE}",
        f"- 截图可读：{readable_count}/10（要求 ≥9）",
        f"- 问题通过：{chat_pass_count}/6（要求 ≥5）",
        f"- 本地引用 [L]：{local_citation_count}/4",
        "",
        "## 10 张题目截图",
        "",
        "| # | 文件 | 可读 | 题目 id | 转写摘要 |",
        "|---|---|---|---|---|",
    ]
    for row in image_rows:
        state = "✅" if row["readable"] else "❌"
        lines.append(
            f"| {row['index']} | `{row['path'].name}` | {state} | {row['question_id'] or '-'} | "
            f"{_snippet(row['text']) or _snippet(row['error'])} |"
        )
    lines += [
        "",
        "## 6 个问题",
        "",
        "| # | 类型 | 通过 | 引用 | 工具 | 回答摘要 |",
        "|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(chat_rows, start=1):
        state = "✅" if row["passed"] else "❌"
        lines.append(
            f"| {index} | {row['kind']} | {state} | {row['citation'] or '-'} | "
            f"{', '.join(row['tool_names']) or '-'} | {_snippet(row['final']) or _snippet('; '.join(row['errors']))} |"
        )

    lines += [
        "",
        "## 结论",
        "",
        f"- 截图 {readable_count}/10，{'达标' if readable_count >= 9 else '未达标'}。",
        f"- 问题 {chat_pass_count}/6，{'达标' if chat_pass_count >= 5 else '未达标'}。",
        f"- 本地问题带 [L] 引用 {local_citation_count}/4。",
        "",
        "> 这些截图是 PIL 生成的印刷体，不是手机实拍；真实拍照另外用 `scripts/check_w3_extras.py --image ...` 验证。",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n报告：{REPORT_PATH}")
    print(f"截图可读 {readable_count}/10；问题通过 {chat_pass_count}/6；本地引用 {local_citation_count}/4")
    return 0 if readable_count >= 9 and chat_pass_count >= 5 and local_citation_count >= 4 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="W3 验收：10 张截图 + 6 个问题")
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--skip-chat", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(not args.skip_images, not args.skip_chat))


if __name__ == "__main__":
    raise SystemExit(main())
