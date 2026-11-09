"""按天累计 token 用量，供用量面板展示。"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.timeutil import local_date
from app.db.models import UsageDaily


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return round(
        input_tokens / 1_000_000 * settings.deepseek_input_price_yuan
        + output_tokens / 1_000_000 * settings.deepseek_output_price_yuan,
        4,
    )


def record_usage(db: Session, user_id: int, input_tokens: int, output_tokens: int) -> None:
    if input_tokens <= 0 and output_tokens <= 0:
        return
    day = local_date()
    row = db.scalar(
        select(UsageDaily).where(
            UsageDaily.user_id == user_id,
            UsageDaily.date == day,
        )
    )
    if row is None:
        row = UsageDaily(
            user_id=user_id,
            date=day,
            turns=0,
            input_tokens=0,
            output_tokens=0,
            cost_yuan=0.0,
        )
        db.add(row)
    row.turns = (row.turns or 0) + 1
    row.input_tokens = (row.input_tokens or 0) + max(0, input_tokens)
    row.output_tokens = (row.output_tokens or 0) + max(0, output_tokens)
    row.cost_yuan = round(
        (row.cost_yuan or 0.0)
        + estimate_cost(max(0, input_tokens), max(0, output_tokens)),
        4,
    )


def usage_summary(db: Session, user_id: int, days: int = 30) -> dict:
    end = local_date()
    start = end - timedelta(days=days - 1)
    rows = db.scalars(
        select(UsageDaily)
        .where(
            UsageDaily.user_id == user_id,
            UsageDaily.date >= start,
            UsageDaily.date <= end,
        )
        .order_by(UsageDaily.date)
    ).all()
    by_date = {row.date: row for row in rows}
    series = []
    cursor = start
    while cursor <= end:
        row = by_date.get(cursor)
        series.append(
            {
                "date": cursor.isoformat(),
                "turns": row.turns if row else 0,
                "input_tokens": row.input_tokens if row else 0,
                "output_tokens": row.output_tokens if row else 0,
                "cost_yuan": row.cost_yuan if row else 0.0,
            }
        )
        cursor += timedelta(days=1)
    return {
        "days": days,
        "total_turns": sum(item["turns"] for item in series),
        "total_input_tokens": sum(item["input_tokens"] for item in series),
        "total_output_tokens": sum(item["output_tokens"] for item in series),
        "total_cost_yuan": round(sum(item["cost_yuan"] for item in series), 4),
        "series": series,
    }
