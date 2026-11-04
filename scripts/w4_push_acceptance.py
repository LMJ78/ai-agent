"""W4 PushPlus 验收：配置通道 → 测试发送 → 创建 N 条到点待办。

用法（在 ai-agent 目录下，先启动服务）：
    $env:PUSHPLUS_TOKEN = "你的 token"
    python scripts/w4_push_acceptance.py --count 10 --interval 5 --wait 180

interval 是两条提醒之间的秒数；wait 是等全部提醒发完的最长秒数。
不传 --wait 时只创建待办，后台任务每 30 秒扫描，到点后自己发。
脚本不会打印 token，也不把 token 写进文件。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db.base import SessionLocal  # noqa: E402
from app.db.models import Todo, User  # noqa: E402


def _channel(client: httpx.Client, token: str) -> None:
    response = client.put(
        "/api/push/channel",
        json={"token": token, "enabled": True},
    )
    if response.status_code != 200:
        raise RuntimeError(f"保存通道失败 {response.status_code}: {response.text[:300]}")
    state = response.json()
    print(f"通道已保存：configured={state.get('configured')} token={state.get('token_masked')}")


def _test_send(client: httpx.Client) -> None:
    response = client.post("/api/push/test")
    if response.status_code != 200:
        raise RuntimeError(f"测试发送失败 {response.status_code}: {response.text[:300]}")
    print("测试消息已发送，请先看微信是否收到。")


def _create_todos(count: int, interval: int, prefix: str) -> list[int]:
    now = datetime.now(timezone.utc)
    ids: list[int] = []
    with SessionLocal() as db:
        user = db.scalar(select(User).order_by(User.id))
        if user is None:
            raise RuntimeError("数据库里没有用户，先启动一次服务初始化 demo 用户")
        for index in range(count):
            due = now + timedelta(seconds=interval * (index + 1))
            todo = Todo(
                user_id=user.id,
                title=f"{prefix}-{index + 1:02d}",
                due_at=due,
                remind_at=due,
                remind_attempts=0,
                done=False,
            )
            db.add(todo)
            db.flush()
            ids.append(todo.id)
        db.commit()
    return ids


def _wait_for(ids: list[int], wait_seconds: int) -> bool:
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        with SessionLocal() as db:
            rows = db.scalars(select(Todo).where(Todo.id.in_(ids))).all()
            sent = sum(1 for row in rows if row.reminded_at is not None)
            failed = sum(1 for row in rows if row.remind_attempts >= 3 and row.reminded_at is None)
        print(f"已提醒 {sent}/{len(ids)}，失败 {failed}/{len(ids)}")
        if sent == len(ids):
            return True
        if failed == len(ids):
            return False
        time.sleep(10)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.getenv("PUSHPLUS_TOKEN", ""))
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--wait", type=int, default=0)
    parser.add_argument("--prefix", default="W4验收")
    args = parser.parse_args()

    token = args.token.strip()
    if not token:
        print("没有 token。先设置：$env:PUSHPLUS_TOKEN = \"你的 token\"")
        print("PushPlus token 在 https://www.pushplus.plus/ 微信扫码登录后复制。")
        return 1
    if args.count < 1 or args.count > 20 or args.interval < 1:
        print("count 取 1–20，interval 至少 1 秒。")
        return 1

    try:
        with httpx.Client(base_url=args.base_url, timeout=60) as client:
            health = client.get("/health")
            if health.status_code != 200:
                raise RuntimeError(f"服务不可用：{health.status_code}")
            _channel(client, token)
            _test_send(client)

        prefix = f"{args.prefix}-{datetime.now().strftime('%H%M%S')}"
        ids = _create_todos(args.count, args.interval, prefix)
        print(f"已创建 {len(ids)} 条待办，前缀 {prefix}，间隔 {args.interval} 秒。")
        if args.wait <= 0:
            print("后台每 30 秒扫描；到点后看微信。要等结果就加 --wait 180。")
            return 0
        ok = _wait_for(ids, args.wait)
        print("全部提醒已发出。" if ok else "超时或部分失败；看服务日志和 todos 表。")
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001 - 验收脚本要打印可读原因
        print(f"验收失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
