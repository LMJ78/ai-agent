"""待办到点提醒：扫描 → PushPlus → 标记，失败最多重试 3 次。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.db.base import SessionLocal
from app.db.models import Todo
from app.services.push import PushError, PushNotConfiguredError, send_to_user
from app.tools.time import CHINA_TZ

logger = logging.getLogger(__name__)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _effective_time(todo: Todo) -> datetime | None:
    return _as_utc(todo.remind_at) or _as_utc(todo.due_at)


def _format_due(value: datetime | None) -> str:
    value = _as_utc(value)
    if value is None:
        return "未设置"
    return value.astimezone(CHINA_TZ).strftime("%m-%d %H:%M")


async def scan_due_todos(now: datetime | None = None) -> dict[str, int]:
    """扫一遍到期待办。没有配置推送的用户直接跳过，不消耗重试次数。"""
    current = _as_utc(now) or datetime.now(timezone.utc)
    result = {"due": 0, "sent": 0, "failed": 0, "skipped": 0}

    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(Todo)
                .where(
                    Todo.done.is_(False),
                    Todo.reminded_at.is_(None),
                    Todo.remind_attempts < 3,
                )
                .order_by(Todo.id)
                .limit(100)
            ).all()
        )

        for todo in rows:
            effective = _effective_time(todo)
            if effective is None or effective > current:
                continue
            result["due"] += 1

            content = f"{todo.title}\n截止：{_format_due(todo.due_at)}"
            try:
                await send_to_user(db, todo.user_id, "伴学提醒", content)
            except PushNotConfiguredError:
                result["skipped"] += 1
                continue
            except PushError as exc:
                todo.remind_attempts += 1
                db.commit()
                result["failed"] += 1
                logger.warning("待办 #%s 推送失败（第 %s 次）：%s", todo.id, todo.remind_attempts, exc)
                continue

            todo.reminded_at = current
            db.commit()
            result["sent"] += 1

    return result


async def reminder_loop() -> None:
    """每 30 秒扫一次。只应在一个进程里跑，避免重复推送。"""
    while True:
        try:
            result = await scan_due_todos()
            if result["sent"] or result["failed"]:
                logger.info("待办提醒扫描：%s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("待办提醒扫描异常")
        await asyncio.sleep(max(5, settings.reminder_scan_seconds))
