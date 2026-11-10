"""只读数据工具：日程、错题本、习惯、新闻、用量。

这些工具只查当前用户自己的数据，不写库；写操作仍然走页面或已有工具。
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.core.timeutil import CHINA_TZ, local_date, to_local
from app.db.base import SessionLocal
from app.db.models import (
    CalendarEvent,
    Habit,
    HabitLog,
    NewsItem,
    ReviewItem,
    UsageDaily,
)
from app.services.calendar import occurrences_between
from app.services.news import NEWS_CATEGORIES, RETENTION_DAYS, list_news
from app.services.usage import usage_summary
from app.tools.base import BaseTool, ToolError, ToolResult

WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _as_local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(CHINA_TZ)


def _clock(value: datetime | None) -> str:
    local = _as_local(value)
    return local.strftime("%H:%M") if local else ""


def _day_label(value: datetime) -> str:
    local = _as_local(value)
    if local is None:
        return ""
    return f"{local.month:02d}-{local.day:02d} {WEEKDAY_NAMES[local.weekday()]}"


def _short(text: object, limit: int = 120) -> str:
    value = " ".join(str(text or "").split())
    return value[:limit] + ("…" if len(value) > limit else "")


def _limit(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


class CalendarTool(BaseTool):
    name = "calendar"
    description = (
        "查看当前用户接下来几天的课程、实验和日程（只读）。"
        "用户问「明天有什么课」「这周日程」「我接下来有什么事」时使用。"
        "不要用它新增或修改日程。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "往后看几天，1–30，默认 7",
            },
            "query": {
                "type": "string",
                "description": "可选关键词，按标题或地点筛选",
            },
        },
        "additionalProperties": False,
    }

    async def run(self, user_id: int, arguments: dict[str, Any]) -> str:
        days = _limit(arguments.get("days"), 7, 1, 30)
        query = str(arguments.get("query") or "").strip().lower()
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)

        with SessionLocal() as db:
            events = db.scalars(
                select(CalendarEvent).where(CalendarEvent.user_id == user_id)
            ).all()
            rows: list[tuple[datetime, CalendarEvent]] = []
            for event in events:
                if query and query not in f"{event.title} {event.location}".lower():
                    continue
                for occurrence in occurrences_between(event, now, end):
                    rows.append((occurrence, event))

        if not rows:
            scope = f"包含「{query}」的" if query else ""
            return f"接下来 {days} 天没有{scope}日程。"

        rows.sort(key=lambda item: item[0])
        lines = [f"接下来 {days} 天的日程（共 {len(rows)} 条）："]
        for occurrence, event in rows[:50]:
            local = _as_local(occurrence)
            if local is None:
                continue
            repeat = "（每周）" if event.recurrence == "weekly" else ""
            place = f" @{event.location}" if event.location else ""
            lines.append(
                f"- {_day_label(occurrence)} {_clock(occurrence)}"
                f"{('-'+_clock(event.end_at)) if event.end_at else ''} "
                f"{event.title}{place}{repeat}"
            )
        return "\n".join(lines)


def _review_line(item: ReviewItem, *, include_answer: bool = False) -> str:
    kind = "回忆卡" if not (item.options or "[]").strip("[] ") else "选择题"
    parts = [
        f"#{item.id}【{item.course or '未分类'}】{_short(item.question, 100)}",
        f"  {kind}，错 {item.wrong_count} 次，复习 {item.review_count} 次，"
        f"连续答对 {item.correct_streak} 次，状态 {item.status}",
    ]
    if item.next_review_at:
        parts.append(f"，下次 {_day_label(item.next_review_at)}")
    if include_answer:
        parts.append(f"\n  参考答案：{_short(item.answer, 600) or '（未填写）'}")
        if item.explanation:
            parts.append(f"\n  解析：{_short(item.explanation, 800)}")
    return "".join(parts)


class ReviewTool(BaseTool):
    name = "review"
    description = (
        "查看当前用户的错题本与复习进度（只读）。"
        "action=stats 看统计；action=due 看今天该复习的题；action=list 按科目/状态列出；"
        "action=get 看某道题的参考答案和解析（需要 item_id）。"
        "用户问「错题本有什么」「今天复习什么」「我哪块薄弱」时使用。"
        "不要用它新增错题；新增错题由页面按钮完成。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["stats", "due", "list", "get"],
                "description": "要查看的内容",
            },
            "course": {"type": "string", "description": "可选，按科目筛选"},
            "status": {
                "type": "string",
                "enum": ["active", "mastered"],
                "description": "list 时的状态，默认 active",
            },
            "item_id": {"type": "integer", "description": "get 时的错题编号"},
            "limit": {
                "type": "integer",
                "description": "最多返回几条，1–20，默认 10",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    async def run(self, user_id: int, arguments: dict[str, Any]) -> str:
        action = str(arguments.get("action") or "").strip().lower()
        course = str(arguments.get("course") or "").strip()
        limit = _limit(arguments.get("limit"), 10, 1, 20)
        now = datetime.now(timezone.utc)

        with SessionLocal() as db:
            if action == "stats":
                active = db.scalar(
                    select(func.count(ReviewItem.id)).where(
                        ReviewItem.user_id == user_id,
                        ReviewItem.status == "active",
                    )
                ) or 0
                mastered = db.scalar(
                    select(func.count(ReviewItem.id)).where(
                        ReviewItem.user_id == user_id,
                        ReviewItem.status == "mastered",
                    )
                ) or 0
                due = db.scalar(
                    select(func.count(ReviewItem.id)).where(
                        ReviewItem.user_id == user_id,
                        ReviewItem.status == "active",
                        ReviewItem.next_review_at <= now,
                    )
                ) or 0
                rows = db.execute(
                    select(ReviewItem.course, func.count(ReviewItem.id))
                    .where(ReviewItem.user_id == user_id)
                    .group_by(ReviewItem.course)
                ).all()
                by_course = "、".join(
                    f"{name or '未分类'} {count} 道" for name, count in rows
                ) or "暂无"
                return (
                    f"错题本：待掌握 {active} 道，已掌握 {mastered} 道，"
                    f"今天该复习 {due} 道。\n按科目：{by_course}"
                )

            if action == "get":
                try:
                    item_id = int(arguments.get("item_id"))
                except (TypeError, ValueError) as exc:
                    raise ToolError("get 需要数字 item_id") from exc
                item = db.scalar(
                    select(ReviewItem).where(
                        ReviewItem.id == item_id,
                        ReviewItem.user_id == user_id,
                    )
                )
                if item is None:
                    raise ToolError(f"没有找到错题 #{item_id}（只能看自己的）")
                return _review_line(item, include_answer=True)

            if action == "due":
                rows = db.scalars(
                    select(ReviewItem)
                    .where(
                        ReviewItem.user_id == user_id,
                        ReviewItem.status == "active",
                        ReviewItem.next_review_at <= now,
                    )
                    .order_by(ReviewItem.next_review_at, ReviewItem.id)
                    .limit(limit)
                ).all()
                if not rows:
                    return "今天没有到期的错题。"
                return "今天该复习的错题：\n" + "\n".join(_review_line(item) for item in rows)

            if action == "list":
                status = str(arguments.get("status") or "active").lower()
                if status not in {"active", "mastered"}:
                    raise ToolError("status 只能是 active / mastered")
                stmt = select(ReviewItem).where(
                    ReviewItem.user_id == user_id, ReviewItem.status == status
                )
                if course:
                    stmt = stmt.where(ReviewItem.course == course)
                rows = db.scalars(
                    stmt.order_by(ReviewItem.next_review_at, ReviewItem.id).limit(limit)
                ).all()
                if not rows:
                    return f"没有找到{'已掌握' if status == 'mastered' else '待掌握'}的错题。"
                return "错题列表：\n" + "\n".join(_review_line(item) for item in rows)

        raise ToolError("action 只能是 stats / due / list / get")


def _habit_streak(db, habit_id: int, today: date) -> int:
    dates = set(
        db.scalars(
            select(HabitLog.log_date).where(
                HabitLog.habit_id == habit_id,
                HabitLog.log_date >= today - timedelta(days=60),
            )
        ).all()
    )
    count = 0
    cursor = today
    while cursor in dates:
        count += 1
        cursor -= timedelta(days=1)
    return count


class HabitsTool(BaseTool):
    name = "habits"
    description = (
        "查看当前用户的习惯打卡（只读）：今天是否打卡、连续天数、本周次数。"
        "用户问「我的习惯」「今天打卡了吗」「连续几天了」时使用。"
        "不要用它创建或打卡；打卡由页面完成。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "day": {
                "type": "string",
                "description": "可选，YYYY-MM-DD；默认今天",
            }
        },
        "additionalProperties": False,
    }

    async def run(self, user_id: int, arguments: dict[str, Any]) -> str:
        today = local_date()
        target = today
        raw_day = str(arguments.get("day") or "").strip()
        if raw_day:
            try:
                target = date.fromisoformat(raw_day)
            except ValueError as exc:
                raise ToolError("day 要用 YYYY-MM-DD 格式") from exc

        with SessionLocal() as db:
            habits = db.scalars(
                select(Habit)
                .where(Habit.user_id == user_id, Habit.active.is_(True))
                .order_by(Habit.sort_order, Habit.id)
            ).all()
            if not habits:
                return "还没有习惯。可以在生活模式「习惯」页添加。"
            done = set(
                db.scalars(
                    select(HabitLog.habit_id).where(
                        HabitLog.user_id == user_id,
                        HabitLog.log_date == target,
                    )
                ).all()
            )
            week_start = today - timedelta(days=today.weekday())
            week_logs = db.scalars(
                select(HabitLog).where(
                    HabitLog.user_id == user_id,
                    HabitLog.log_date >= week_start,
                    HabitLog.log_date <= today,
                )
            ).all()
            week_counts: dict[int, int] = {}
            for log in week_logs:
                week_counts[log.habit_id] = week_counts.get(log.habit_id, 0) + 1

            lines = [f"{target.isoformat()} 的习惯打卡："]
            for habit in habits:
                mark = "✅" if habit.id in done else "○"
                lines.append(
                    f"{mark} {habit.icon} {habit.name}："
                    f"连续 {_habit_streak(db, habit.id, target)} 天，"
                    f"本周 {week_counts.get(habit.id, 0)} 次"
                )
            return "\n".join(lines)


class NewsTool(BaseTool):
    name = "news"
    description = (
        "查看 Agent 里最近 3 天的每日新闻（只读），按科技/AI、国内、国际、财经、体育分类，"
        "每条带标题、来源和原文链接。用户问「今天有什么新闻」「最近科技新闻」时使用。"
        "不要用它刷新或推送新闻。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "可选，按分类筛选，例如 科技/AI、国内、国际、财经、体育",
            },
            "days": {
                "type": "integer",
                "description": "看最近几天，1–3，默认 1（今天）",
            },
            "limit": {
                "type": "integer",
                "description": "每个分类最多几条，1–5，默认 2",
            },
        },
        "additionalProperties": False,
    }

    async def run(self, user_id: int, arguments: dict[str, Any]) -> ToolResult:
        category = str(arguments.get("category") or "").strip()
        days = _limit(arguments.get("days"), 1, 1, RETENTION_DAYS)
        limit = _limit(arguments.get("limit"), 2, 1, 5)
        valid = {name for name, _ in NEWS_CATEGORIES}
        if category and category not in valid:
            raise ToolError(f"分类只能是：{'、'.join(valid)}")

        with SessionLocal() as db:
            groups = list_news(db, user_id, days=days)

        lines: list[str] = []
        citations: list[dict[str, Any]] = []
        index = 1
        for group in groups:
            chunks: list[str] = []
            for item in group["categories"]:
                if category and item["name"] != category:
                    continue
                entries = item["items"][:limit]
                if not entries:
                    continue
                chunks.append(f"【{item['name']}】")
                for news in entries:
                    label = f"W{index}"
                    chunks.append(
                        f"- [{label}] {_short(news['title'], 120)}\n"
                        f"  来源：{news['source'] or '未知'}  {news['url']}"
                    )
                    citations.append(
                        {
                            "type": "web",
                            "label": label,
                            "title": news["title"],
                            "url": news["url"],
                            "snippet": _short(news.get("summary"), 160),
                        }
                    )
                    index += 1
            if chunks:
                lines.append(f"{group['date']}\n" + "\n".join(chunks))

        if not lines:
            return "这几天还没有新闻。可以打开「每日新闻」页刷新一次。"
        return ToolResult("\n\n".join(lines), citations)


class UsageTool(BaseTool):
    name = "usage"
    description = (
        "查看当前用户最近一段时间的 AI 用量（只读）：轮次、输入/输出 token、估算费用。"
        "用户问「我用了多少 token」「这个月花了多少」时使用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "统计最近几天，1–90，默认 30",
            }
        },
        "additionalProperties": False,
    }

    async def run(self, user_id: int, arguments: dict[str, Any]) -> str:
        days = _limit(arguments.get("days"), 30, 1, 90)
        with SessionLocal() as db:
            data = usage_summary(db, user_id, days)
        if data["total_turns"] == 0:
            return f"最近 {days} 天还没有用量记录。"
        active_days = [item for item in data["series"] if item["turns"]]
        recent = "；".join(
            f"{item['date']} {item['turns']} 轮"
            for item in active_days[-7:]
        )
        return (
            f"最近 {days} 天：{data['total_turns']} 轮，"
            f"输入 {data['total_input_tokens']} tokens，"
            f"输出 {data['total_output_tokens']} tokens，"
            f"估算 ¥{data['total_cost_yuan']:.4f}。\n"
            f"最近有记录的日子：{recent or '无'}"
        )
