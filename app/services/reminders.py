"""待办到点提醒：扫描 → PushPlus → 标记，失败最多重试 3 次。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.config import settings
from app.core.timeutil import local_date
from app.db.base import SessionLocal
from app.db.models import CalendarEvent, Habit, HabitLog, ReviewItem, Todo
from app.services.briefs import send_due_briefs
from app.services.calendar import next_occurrence
from app.services.news import purge_all_old_news
from app.services.notifications import create_notification
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


def _created_tag(value: datetime | None) -> str:
    """SQLite 会复用被删除的最大 id；把创建时间带进去，避免旧通知挡住新记录。"""
    return value.isoformat() if value is not None else "na"


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
            create_notification(
                db,
                user_id=todo.user_id,
                kind="todo",
                title="待办提醒",
                body=content,
                link="calendar",
                dedupe_key=f"todo:{todo.id}:{_created_tag(todo.created_at)}:{effective.isoformat()}",
            )
            try:
                await send_to_user(db, todo.user_id, "伴学提醒", content)
            except PushNotConfiguredError:
                # 没有推送通道也算已提醒：站内通知已经落库，不再每 30 秒重复扫。
                todo.reminded_at = current
                db.commit()
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


async def scan_due_events(now: datetime | None = None) -> dict[str, int]:
    """课程/日程开始前 calendar_reminder_minutes 分钟推送。"""
    current = _as_utc(now) or datetime.now(timezone.utc)
    window = current.timestamp() + settings.calendar_reminder_minutes * 60
    result = {"due": 0, "sent": 0, "failed": 0, "skipped": 0}

    with SessionLocal() as db:
        rows = db.scalars(select(CalendarEvent)).all()
        for event in rows:
            occurrence = next_occurrence(event, current)
            # 一次性事件已经过去就别补发；只提醒即将开始或刚刚开始的。
            if occurrence.timestamp() < current.timestamp() - 60:
                continue
            if occurrence.timestamp() > window:
                continue
            if event.last_reminded_for is not None:
                last = _as_utc(event.last_reminded_for)
                if last is not None and abs((last - occurrence).total_seconds()) < 60:
                    continue
            result["due"] += 1
            local = occurrence.astimezone(CHINA_TZ)
            where = f"\n地点：{event.location}" if event.location else ""
            content = f"{local:%m-%d %H:%M} {event.title}{where}"
            create_notification(
                db,
                user_id=event.user_id,
                kind="event",
                title="日程提醒",
                body=content,
                link="calendar",
                dedupe_key=f"event:{event.id}:{_created_tag(event.created_at)}:{occurrence.isoformat()}",
            )
            try:
                await send_to_user(db, event.user_id, "日程提醒", content)
            except PushNotConfiguredError:
                event.last_reminded_for = occurrence
                db.commit()
                result["skipped"] += 1
                continue
            except PushError:
                event.last_reminded_for = occurrence
                db.commit()
                result["failed"] += 1
                continue
            event.last_reminded_for = occurrence
            db.commit()
            result["sent"] += 1
    return result


async def scan_due_habits(now: datetime | None = None) -> dict[str, int]:
    """每天到点提醒还没打卡的习惯；站内通知先落库，推送可选。"""
    current = (_as_utc(now) or datetime.now(timezone.utc)).astimezone(CHINA_TZ)
    result = {"due": 0, "created": 0, "pushed": 0}
    with SessionLocal() as db:
        habits = db.scalars(
            select(Habit).where(Habit.active.is_(True), Habit.remind_at != "")
        ).all()
        for habit in habits:
            try:
                target = datetime.strptime(habit.remind_at, "%H:%M").time()
            except ValueError:
                continue
            if current.time() < target:
                continue
            done = db.scalar(
                select(HabitLog.id).where(
                    HabitLog.habit_id == habit.id,
                    HabitLog.user_id == habit.user_id,
                    HabitLog.log_date == current.date(),
                )
            )
            if done is not None:
                continue
            result["due"] += 1
            item = create_notification(
                db,
                user_id=habit.user_id,
                kind="habit",
                title="习惯打卡提醒",
                body=f"{habit.icon} {habit.name}\n今天还没打卡，花一分钟完成它。",
                link="habits",
                dedupe_key=f"habit:{habit.id}:{_created_tag(habit.created_at)}:{current.date().isoformat()}",
            )
            if item is None:
                continue
            result["created"] += 1
            db.commit()
            try:
                await send_to_user(
                    db,
                    habit.user_id,
                    "习惯打卡提醒",
                    f"{habit.icon} {habit.name}\n今天还没打卡。",
                )
                result["pushed"] += 1
            except (PushNotConfiguredError, PushError):
                pass
    return result


async def scan_due_reviews(now: datetime | None = None) -> dict[str, int]:
    """每天给有到期错题的用户发一条站内提醒。"""
    current = _as_utc(now) or datetime.now(timezone.utc)
    today = current.astimezone(CHINA_TZ).date()
    result = {"users": 0, "created": 0}
    with SessionLocal() as db:
        rows = db.execute(
            select(ReviewItem.user_id, func.count(ReviewItem.id))
            .where(
                ReviewItem.status == "active",
                ReviewItem.next_review_at <= current,
            )
            .group_by(ReviewItem.user_id)
        ).all()
        for user_id, count in rows:
            result["users"] += 1
            item = create_notification(
                db,
                user_id=user_id,
                kind="review",
                title=f"今天有 {count} 道错题待复习",
                body="按 3 / 7 / 14 / 30 天的节奏过一遍，别堆到考前。",
                link="review",
                dedupe_key=f"review:{today.isoformat()}",
            )
            if item is not None:
                result["created"] += 1
                db.commit()
    return result


async def reminder_loop() -> None:
    """每 30 秒扫一次。只应在一个进程里跑，避免重复推送。"""
    while True:
        try:
            result = await scan_due_todos()
            if result["sent"] or result["failed"]:
                logger.info("待办提醒扫描：%s", result)
            event_result = await scan_due_events()
            if event_result["sent"] or event_result["failed"]:
                logger.info("日程提醒扫描：%s", event_result)
            habit_result = await scan_due_habits()
            if habit_result["created"]:
                logger.info("习惯提醒扫描：%s", habit_result)
            review_result = await scan_due_reviews()
            if review_result["created"]:
                logger.info("错题提醒扫描：%s", review_result)
            await send_due_briefs()
            purge_all_old_news()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("待办提醒扫描异常")
        await asyncio.sleep(max(5, settings.reminder_scan_seconds))
