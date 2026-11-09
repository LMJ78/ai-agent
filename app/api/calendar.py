"""课表 / 日程接口：手动添加 + ICS 导入 + 未来 occurrence 展开。"""

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.timeutil import to_local, to_utc
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
