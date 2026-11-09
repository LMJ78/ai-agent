"""本地时间工具。

数据库统一存 UTC；课表、简报、习惯打卡都按用户所在时区（默认上海）展示。
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

CHINA_TZ = ZoneInfo("Asia/Shanghai")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(value: datetime) -> datetime:
    """naive 时间按上海时区理解，再转 UTC；aware 时间直接换算。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=CHINA_TZ)
    return value.astimezone(timezone.utc)


def to_local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(CHINA_TZ)


def local_date(value: datetime | None = None) -> date:
    return (to_local(value) or datetime.now(CHINA_TZ)).date()


def parse_hhmm(value: str, fallback: time) -> time:
    try:
        hour, minute = value.strip().split(":", 1)
        return time(int(hour), int(minute))
    except (ValueError, AttributeError):
        return fallback


def at_local_day(day: date, hhmm: str, fallback: time) -> datetime:
    """返回某天本地 HH:MM 对应的 UTC 时间。"""
    return to_utc(datetime.combine(day, parse_hhmm(hhmm, fallback)))


def next_weekly_occurrence(
    start_at: datetime,
    weekday: int,
    now: datetime | None = None,
) -> datetime:
    """按「每周 weekday」找下一次发生时间，返回 UTC。"""
    current = to_local(now or now_utc())
    start_local = to_local(start_at)
    assert current is not None and start_local is not None

    # 先对齐到 start_at 所在周的周一，再往目标 weekday 推。
    monday = start_local.date() - timedelta(days=start_local.weekday())
    target_day = monday + timedelta(days=weekday)
    candidate = datetime.combine(target_day, start_local.timetz().replace(tzinfo=None))
    candidate = candidate.replace(tzinfo=CHINA_TZ)
    if candidate < start_local:
        candidate += timedelta(days=7)
    while candidate < current:
        candidate += timedelta(days=7)
    return candidate.astimezone(timezone.utc)
