"""每日简报 / 晚间复盘：模板化生成，推送时间由用户设置决定。"""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import CHINA_TZ, at_local_day, local_date, parse_hhmm
from app.db.models import CalendarEvent, ReviewItem, Todo, User, UserSettings
from app.services.calendar import occurrences_between
from app.services.push import PushError, PushNotConfiguredError, send_to_user
from app.tools.web_search import search_web


def get_or_create_settings(db: Session, user_id: int) -> UserSettings:
    settings = db.scalar(select(UserSettings).where(UserSettings.user_id == user_id))
    if settings is None:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def _today_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    local = (now or datetime.now(timezone.utc)).astimezone(CHINA_TZ)
    start = datetime.combine(local.date(), time.min, tzinfo=CHINA_TZ)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(
        timezone.utc
    )


async def build_morning_brief(db: Session, user: User, cfg: UserSettings) -> tuple[str, str]:
    start, end = _today_bounds()
    events = db.scalars(
        select(CalendarEvent).where(CalendarEvent.user_id == user.id)
    ).all()
    today_events: list[str] = []
    for event in events:
        for occurrence in occurrences_between(event, start, end):
            local = occurrence.astimezone(CHINA_TZ)
            where = f" @ {event.location}" if event.location else ""
            today_events.append(f"{local:%H:%M} {event.title}{where}")

    todos = db.scalars(
        select(Todo).where(
            Todo.user_id == user.id,
            Todo.done.is_(False),
            Todo.due_at.is_not(None),
            Todo.due_at >= start,
            Todo.due_at < end,
        )
    ).all()

    lines = [f"早上好，{user.display_name or user.username}。", ""]
    lines.append("今天的安排：")
    lines.extend([f"- {item}" for item in today_events] or ["- 今天没有课表/日程。"])
    lines.append("")
    lines.append("今天到期的待办：")
    lines.extend(
        [f"- {todo.title}" for todo in todos] or ["- 没有到期的待办。"]
    )

    if cfg.news_topics.strip():
        try:
            results = await search_web(
                f"今天值得关注的新闻：{cfg.news_topics.strip()}", max_results=3
            )
            if results:
                lines.extend(["", "给你挑的几条新闻："])
                for index, item in enumerate(results, start=1):
                    lines.append(f"[W{index}] {item.get('title', '')}")
                    lines.append(str(item.get("url", "")))
        except Exception:  # noqa: BLE001
            # 新闻失败不影响简报主体。
            pass

    lines.extend(["", "今天也一起把最重要的一件事做好。"])
    return "早上好，今天的安排来了", "\n".join(lines)


async def build_evening_review(db: Session, user: User, cfg: UserSettings) -> tuple[str, str]:
    start, end = _today_bounds()
    done = db.scalars(
        select(Todo).where(
            Todo.user_id == user.id,
            Todo.done.is_(True),
            Todo.completed_at.is_not(None),
            Todo.completed_at >= start,
            Todo.completed_at < end,
        )
    ).all()
    pending = db.scalars(
        select(Todo).where(Todo.user_id == user.id, Todo.done.is_(False))
    ).all()
    reviewed = db.scalar(
        select(ReviewItem)
        .where(
            ReviewItem.user_id == user.id,
            ReviewItem.last_reviewed_at.is_not(None),
            ReviewItem.last_reviewed_at >= start,
        )
        .limit(1)
    )
    lines = [
        f"晚上好，{user.display_name or user.username}。",
        "",
        f"今天完成了 {len(done)} 件待办，还有 {len(pending)} 件没做完。",
        f"今天复习了错题：{'有' if reviewed else '还没有'}。",
        "",
        "用一句话复盘今天：哪件事做得不错？哪件事明天要换个做法？",
        "不用急着回答，想清楚就睡。",
    ]
    return "晚间复盘，今天辛苦了", "\n".join(lines)


async def send_due_briefs(now: datetime | None = None) -> None:
    from app.db.base import SessionLocal

    current = (now or datetime.now(timezone.utc)).astimezone(CHINA_TZ)
    with SessionLocal() as db:
        rows = db.scalars(select(UserSettings)).all()
        for cfg in rows:
            user = db.get(User, cfg.user_id)
            if user is None:
                continue
            today = current.date()
            due: list[str] = []
            if cfg.morning_enabled and cfg.last_morning_date != today:
                target = at_local_day(today, cfg.morning_time, time(7, 30))
                if current >= target.astimezone(CHINA_TZ):
                    due.append("morning")
            if cfg.evening_enabled and cfg.last_evening_date != today:
                target = at_local_day(today, cfg.evening_time, time(21, 30))
                if current >= target.astimezone(CHINA_TZ):
                    due.append("evening")

            for kind in due:
                try:
                    if kind == "morning":
                        title, content = await build_morning_brief(db, user, cfg)
                    else:
                        title, content = await build_evening_review(db, user, cfg)
                    await send_to_user(db, user.id, title, content)
                    if kind == "morning":
                        cfg.last_morning_date = today
                    else:
                        cfg.last_evening_date = today
                    db.commit()
                except PushNotConfiguredError:
                    break
                except PushError:
                    db.rollback()
                    break
                except Exception:  # noqa: BLE001
                    db.rollback()
