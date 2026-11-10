"""课表 / 日程接口：手动添加 + ICS 导入 + 未来 occurrence 展开。"""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.vision import (
    VisionError,
    VisionNotConfiguredError,
    extract_timetable,
)
from app.core.deps import get_current_user
from app.core.timeutil import CHINA_TZ, to_local, to_utc
from app.db.base import get_db
from app.db.models import CalendarEvent, User
from app.services.calendar import next_occurrence, occurrences_between, parse_ics

router = APIRouter()


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    location: str = Field(default="", max_length=255)
    course: str = Field(default="", max_length=64)
    start_at: datetime
    end_at: datetime | None = None
    recurrence: Literal["none", "weekly"] = "none"
    weekday: int | None = Field(default=None, ge=0, le=6)
    note: str = Field(default="", max_length=2000)


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _event_dict(event: CalendarEvent) -> dict:
    return {
        "id": event.id,
        "title": event.title,
        "location": event.location,
        "course": event.course,
        "start_at": _iso(event.start_at),
        "end_at": _iso(event.end_at),
        "recurrence": event.recurrence,
        "weekday": event.weekday,
        "note": event.note,
    }


def _clock(value: object):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError:
        return None


def _own(db: Session, user_id: int, event_id: int) -> CalendarEvent:
    event = db.scalar(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id,
            CalendarEvent.user_id == user_id,
        )
    )
    if event is None:
        raise HTTPException(status_code=404, detail="日程不存在")
    return event


@router.get("/calendar/events")
def list_events(
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days)
    rows = db.scalars(
        select(CalendarEvent).where(CalendarEvent.user_id == user.id)
    ).all()
    items: list[dict] = []
    for event in rows:
        for occurrence in occurrences_between(event, start, end):
            items.append(
                {
                    **_event_dict(event),
                    "start_at": _iso(occurrence),
                    "end_at": _iso(
                        occurrence
                        + (event.end_at - event.start_at)
                        if event.end_at and event.start_at
                        else None
                    ),
                    "occurrence": True,
                }
            )
    items.sort(key=lambda item: item["start_at"])
    return items[:300]


@router.get("/calendar/upcoming")
def upcoming_events(
    days: int = Query(default=7, ge=1, le=60),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_events(days=days, user=user, db=db)


@router.post("/calendar/events", status_code=201)
def create_event(
    payload: EventIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    start = to_utc(payload.start_at)
    weekday = payload.weekday
    if weekday is None:
        weekday = to_local(start).weekday() if to_local(start) else None
    event = CalendarEvent(
        user_id=user.id,
        title=payload.title.strip(),
        location=payload.location.strip(),
        course=payload.course.strip(),
        start_at=start,
        end_at=to_utc(payload.end_at) if payload.end_at else None,
        recurrence=payload.recurrence,
        weekday=weekday if payload.recurrence == "weekly" else None,
        note=payload.note.strip(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {**_event_dict(event), "next_at": _iso(next_occurrence(event))}


@router.patch("/calendar/events/{event_id}")
def update_event(
    event_id: int,
    payload: EventIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    event = _own(db, user.id, event_id)
    start = to_utc(payload.start_at)
    event.title = payload.title.strip()
    event.location = payload.location.strip()
    event.course = payload.course.strip()
    event.start_at = start
    event.end_at = to_utc(payload.end_at) if payload.end_at else None
    event.recurrence = payload.recurrence
    event.weekday = (
        payload.weekday
        if payload.weekday is not None
        else (to_local(start).weekday() if to_local(start) else None)
    ) if payload.recurrence == "weekly" else None
    event.note = payload.note.strip()
    event.last_reminded_for = None
    db.commit()
    db.refresh(event)
    return {**_event_dict(event), "next_at": _iso(next_occurrence(event))}


@router.delete("/calendar/events/{event_id}")
def delete_event(
    event_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    event = _own(db, user.id, event_id)
    db.delete(event)
    db.commit()
    return {"deleted": event_id}


@router.post("/calendar/import-image", status_code=201)
async def import_timetable_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="只支持 JPG/PNG/WebP 课表图片")
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片不能超过 10MB")

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        try:
            items = await extract_timetable(tmp_path)
        except VisionNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except VisionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    if not items:
        raise HTTPException(status_code=400, detail="没有从图片里识别到课程，请换一张清晰的课表")

    now = datetime.now(CHINA_TZ)
    existing = {
        (event.title, event.weekday, to_local(event.start_at).strftime("%H:%M"))
        for event in db.scalars(
            select(CalendarEvent).where(CalendarEvent.user_id == user.id)
        ).all()
        if event.weekday is not None
    }
    created: list[CalendarEvent] = []
    skipped = 0
    for item in items[:50]:
        title = str(item.get("title") or "").strip()[:255]
        try:
            weekday = int(item.get("weekday"))
        except (TypeError, ValueError):
            continue
        start_time = _clock(item.get("start_time"))
        if not title or not start_time or not 1 <= weekday <= 7:
            continue
        end_time = _clock(item.get("end_time"))
        if end_time is None or end_time <= start_time:
            end_time = (datetime.combine(now.date(), start_time) + timedelta(minutes=90)).time()

        key = (title, weekday - 1, start_time.strftime("%H:%M"))
        if key in existing:
            skipped += 1
            continue

        day = now.date() + timedelta(days=(weekday - 1 - now.weekday()) % 7)
        start_local = datetime.combine(day, start_time, tzinfo=CHINA_TZ)
        if start_local < now:
            start_local += timedelta(days=7)
        end_local = datetime.combine(start_local.date(), end_time, tzinfo=CHINA_TZ)
        if end_local <= start_local:
            end_local = start_local + timedelta(minutes=90)

        event = CalendarEvent(
            user_id=user.id,
            title=title,
            location=str(item.get("location") or "").strip()[:255],
            course="",
            start_at=to_utc(start_local),
            end_at=to_utc(end_local),
            recurrence="weekly",
            weekday=weekday - 1,
            note="从课表图片导入",
        )
        db.add(event)
        created.append(event)
        existing.add(key)

    if not created:
        raise HTTPException(
            status_code=400,
            detail=f"识别到 {len(items)} 条，但没有可导入的新课程（可能已经导入过）",
        )
    db.commit()
    for event in created:
        db.refresh(event)
    return {
        "imported": len(created),
        "skipped": skipped,
        "events": [{**_event_dict(event), "next_at": _iso(next_occurrence(event))} for event in created],
    }


@router.post("/calendar/import")
async def import_ics(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not (file.filename or "").lower().endswith(".ics"):
        raise HTTPException(status_code=400, detail="只支持 .ics 日历文件")
    raw = await file.read()
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="ICS 文件不能超过 2MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("gbk", errors="replace")
    events = parse_ics(text)
    if not events:
        raise HTTPException(status_code=400, detail="没有解析到日程")
    for item in events:
        db.add(
            CalendarEvent(
                user_id=user.id,
                title=item["title"],
                location=item["location"],
                course="",
                start_at=item["start_at"],
                end_at=item["end_at"],
                recurrence=item["recurrence"],
                weekday=item["weekday"],
                note=item["note"],
            )
        )
    db.commit()
    return {"imported": len(events)}
