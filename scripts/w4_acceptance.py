"""W4 解题老师验收：10 道题，每题走 hint → step → answer。

8 道本地题要求答案里出现 [L] 引用；2 道资料外题只检查「有没有正面回答」，
正确性留给人工看报告。脚本会创建 confirmed 题目，跑完删掉题目，不删会话。

用法（服务先跑在 8000）：
    python scripts/w4_acceptance.py
    python scripts/w4_acceptance.py --limit 2
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import httpx

COURSE = "算法设计与分析"
REPORT = Path("data/acceptance/w4_report.md")
TRANSCRIPT_DIR = Path("data/acceptance/w4")

QUESTIONS = [
    {
        "title": "动态规划的基本思想",
        "text": "动态规划的基本思想是什么？它和分治有什么共同点？",
        "chapter": "ch03",
        "local": True,
    },
    {
        "title": "0-1 背包状态转移方程",
        "text": "0-1 背包问题的状态转移方程怎么推导？",
        "chapter": "ch03",
        "local": True,
    },
    {
        "title": "快速排序复杂度",
        "text": "快速排序的平均时间复杂度和最坏时间复杂度分别是多少？",
        "chapter": "ch02",
        "local": True,
    },
    {
        "title": "归并排序复杂度",
        "text": "归并排序的时间复杂度为什么是 O(n log n)？",
        "chapter": "ch02",
        "local": True,
    },
    {
        "title": "二分查找前提",
        "text": "二分查找需要满足什么前提条件？",
        "chapter": "ch02",
        "local": True,
    },
    {
        "title": "递归与分治",
        "text": "递归和分治是什么关系？",
        "chapter": "ch01",
        "local": True,
    },
    {
        "title": "贪心与动态规划",
        "text": "贪心算法和动态规划的核心区别是什么？",
        "chapter": "ch03",
        "local": True,
    },
    {
        "title": "时间复杂度",
        "text": "什么是算法的时间复杂度？为什么要用大 O 表示？",
        "chapter": "ch01",
        "local": True,
    },
    {
        "title": "资料外：Shor 算法",
        "text": "量子计算中的 Shor 算法时间复杂度是多少？",
        "chapter": "",
        "local": False,
    },
    {
        "title": "资料外：教室",
        "text": "明天算法课在哪个教室？",
        "chapter": "",
        "local": False,
    },
]

STAGES = [
    ("hint", "给我一个提示，先不要直接给答案。"),
    ("step", "继续下一步，但还是不要直接给最终答案。"),
    ("answer", "直接看答案。"),
]


def _chat(
    client: httpx.Client,
    *,
    question_id: int,
    message: str,
    stage: str,
    session_id: int | None,
) -> tuple[str, int | None]:
    payload = {
        "message": message,
        "mode": "study",
        "course": COURSE,
        "question_id": question_id,
        "teaching_stage": stage,
    }
    if session_id is not None:
        payload["session_id"] = session_id

    parts: list[str] = []
    with client.stream("POST", "/api/chat", json=payload) as response:
        if response.status_code != 200:
            raise RuntimeError(f"chat {response.status_code}: {response.read().decode('utf-8', 'replace')[:300]}")
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            if "session_id" in event:
                session_id = int(event["session_id"])
            if "delta" in event:
                parts.append(str(event["delta"]))
            if event.get("type") == "error":
                raise RuntimeError(event.get("message", "模型返回错误"))
    return "".join(parts).strip(), session_id


def _create_question(client: httpx.Client, item: dict) -> int:
    created = client.post(
        "/api/questions/text",
        json={
            "text": item["text"],
            "course": COURSE,
            "chapter": item["chapter"],
        },
    )
    if created.status_code != 200:
        raise RuntimeError(f"创建题目失败 {created.status_code}: {created.text[:200]}")
    question_id = int(created.json()["id"])
    confirmed = client.post(f"/api/questions/{question_id}/confirm", json={})
    if confirmed.status_code != 200:
        raise RuntimeError(f"确认题目失败 {confirmed.status_code}: {confirmed.text[:200]}")
    return question_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    items = QUESTIONS[: max(1, min(args.limit, len(QUESTIONS)))]
    rows: list[dict] = []

    with httpx.Client(base_url=args.base_url, timeout=180) as client:
        health = client.get("/health")
        if health.status_code != 200:
            print(f"服务不可用：{health.status_code} {health.text[:200]}")
            return 1

        for index, item in enumerate(items, start=1):
            question_id = None
            row = {
                "index": index,
                "title": item["title"],
                "local": item["local"],
                "hint": "FAIL",
                "step": "FAIL",
                "answer": "FAIL",
                "citation": "-",
                "note": "",
                "transcript": "",
            }
            try:
                question_id = _create_question(client, item)
                session_id = None
                texts: dict[str, str] = {}
                for stage, message in STAGES:
                    text, session_id = _chat(
                        client,
                        question_id=question_id,
                        message=message,
                        stage=stage,
                        session_id=session_id,
                    )
                    texts[stage] = text
                    if not text:
                        raise RuntimeError(f"{stage} 返回空")
                    if stage in {"hint", "step"} and "【答案】" in text:
                        raise RuntimeError(f"{stage} 提前给了完整答案")
                    if stage == "answer" and "【答案】" not in text:
                        raise RuntimeError("answer 没有使用【答案】格式")

                row["hint"] = "PASS"
                row["step"] = "PASS"
                row["answer"] = "PASS"
                if item["local"]:
                    row["citation"] = "PASS" if "[L" in texts["answer"] else "FAIL"
                else:
                    row["citation"] = "N/A"
                row["note"] = texts["answer"].replace("\n", " ")[:100]

                TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
                transcript = TRANSCRIPT_DIR / f"q{index:02d}.md"
                transcript.write_text(
                    "\n".join(
                        [
                            f"# {index}. {item['title']}",
                            "",
                            f"- 课程：{COURSE}",
                            f"- 章节：{item['chapter'] or '资料外'}",
                            f"- 题目：{item['text']}",
                            "",
                            "## hint",
                            "",
                            texts["hint"],
                            "",
                            "## step",
                            "",
                            texts["step"],
                            "",
                            "## answer",
                            "",
                            texts["answer"],
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                row["transcript"] = transcript.as_posix()
            except Exception as exc:  # noqa: BLE001 - 验收脚本要把每种失败记进报告
                row["note"] = str(exc)[:200]
            finally:
                if question_id is not None:
                    client.delete(f"/api/questions/{question_id}")
            rows.append(row)
            print(f"[{index:02d}/{len(items)}] {row['title']}: hint={row['hint']} step={row['step']} answer={row['answer']} cite={row['citation']}")

    local_rows = [row for row in rows if row["local"]]
    local_pass = sum(1 for row in local_rows if row["citation"] == "PASS")
    stage_pass = sum(1 for row in rows if row["hint"] == row["step"] == row["answer"] == "PASS")
    answer_pass = sum(1 for row in rows if row["answer"] == "PASS")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# W4 解题老师验收报告",
        "",
        f"- 时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 服务：{args.base_url}",
        f"- 题目：{len(rows)} 道（本地 {len(local_rows)}，资料外 {len(rows) - len(local_rows)}）",
        f"- 三阶段完整：{stage_pass}/{len(rows)}",
        f"- 答案格式：{answer_pass}/{len(rows)}",
        f"- 本地引用：{local_pass}/{len(local_rows)}",
        "",
        "| # | 题目 | hint | step | answer | [L] | 完整对话 | 备注 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        transcript = row.get("transcript", "")
        link = f"[q{row['index']:02d}](w4/q{row['index']:02d}.md)" if transcript else "-"
        lines.append(
            f"| {row['index']} | {row['title']} | {row['hint']} | {row['step']} | "
            f"{row['answer']} | {row['citation']} | {link} | {row['note']} |"
        )
    lines += [
        "",
        "> 这是结构/引用验收；答案是否正确要人工看「完整对话」里的 hint/step/answer。",
        "> 资料外的两道题不要求 [L]，只要求不硬编。",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n报告：{REPORT}")
    print(f"三阶段完整 {stage_pass}/{len(rows)}；本地引用 {local_pass}/{len(local_rows)}")
    return 0 if stage_pass == len(rows) and (not local_rows or local_pass == len(local_rows)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
