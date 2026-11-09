"""课表/日程：ICS 解析与重复事件展开。"""

import re
from datetime import date, datetime, time, timedelta, timezone

from app.core.timeutil import CHINA_TZ, next_weekly_occurrence, to_local, to_utc

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_dt(value: str) -> datetime | None:
    value = value.strip()
    # 20260901T080000 / 20260901T080000Z / 20260901
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            parsed = datetime.strptime(value.replace("Z", ""), fmt)
        except ValueError:
            continue
        if fmt == "%Y%m%d":
            return to_utc(datetime.combine(parsed.date(), time(0, 0)))
        if value.endswith("Z"):
            return parsed.replace(tzinfo=timezone.utc)
        return to_utc(parsed)
    return None


def parse_ics(text: str) -> list[dict]:
    events: list[dict] = []
    current: dict | None = None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current and current.get("start_at"):
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue

        key, value = line.split(":", 1)
        name = key.split(";", 1)[0].upper()
        if name == "SUMMARY":
            current["title"] = value.strip()[:255]
        elif name == "LOCATION":
            current["location"] = value.strip()[:255]
        elif name == "DESCRIPTION":
            current["note"] = value.strip()[:2000]
        elif name == "DTSTART":
            current["start_at"] = _parse_dt(value)
        elif name == "DTEND":
            current["end_at"] = _parse_dt(value)
        elif name == "RRULE":
            current["rrule"] = value.upper()

    result: list[dict] = []
    for event in events:
        start = event.get("start_at")
        if start is None:
            continue
        rrule = event.get("rrule", "")
        recurrence = "weekly" if "FREQ=WEEKLY" in rrule else "none"
        weekday = to_local(start).weekday() if start else None
        match = re.search(r"BYDAY=([A-Z,]+)", rrule)
        if match:
            first = match.group(1).split(",")[0][-2:]
            weekday = WEEKDAYS.get(first, weekday)
        result.append(
            {
                "title": event.get("title") or "未命名日程",
                "location": event.get("location", ""),
                "note": event.get("note", ""),
                "start_at": start,
                "end_at": event.get("end_at"),
                "recurrence": recurrence,
                "weekday": weekday,
            }
        )
    return result


def _event_weekday(event) -> int | None:
    """周几统一用 Python 的 0=周一；前端只传重复、不传 weekday 时从开始时间推断。"""
    if event.recurrence != "weekly":
        return None
    if event.weekday is not None:
        return event.weekday % 7
    start = event.start_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    local = to_local(start)
    return local.weekday() if local else None


def next_occurrence(event, now: datetime | None = None) -> datetime:
    """返回事件的下一次发生时间（UTC）。"""
    now = now or datetime.now(timezone.utc)
    weekday = _event_weekday(event)
    if weekday is not None:
        return next_weekly_occurrence(event.start_at, weekday, now)
    start = event.start_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return start


def occurrences_between(event, start: datetime, end: datetime) -> list[datetime]:
    result: list[datetime] = []
    current = next_occurrence(event, start - timedelta(seconds=1))
    weekday = _event_weekday(event)
    # 单次事件只出现一次；重复事件最多展开 60 次，防止死循环。
    for _ in range(60):
        if current > end:
            break
        if current >= start:
            result.append(current)
        if weekday is None:
            break
        # 加 1 秒，避免 next_weekly_occurrence 在边界上返回同一个时刻。
        current = next_weekly_occurrence(event.start_at, weekday, current + timedelta(seconds=1))
    return result
