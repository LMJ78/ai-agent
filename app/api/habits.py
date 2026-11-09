"""生活模式习惯打卡。"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.timeutil import local_date
from app.db.base import get_db
from app.db.models import Habit, HabitLog, User

router = APIRouter()


class HabitIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    icon: str = Field(default="✅", max_length=16)


def _streak(db: Session, habit_id: int, today: date) -> int:
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


@router.get("/habits")
def list_habits(
    day: str | None = Query(default=None, description="YYYY-MM-DD，默认今天"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    today = local_date()
    target = date.fromisoformat(day) if day else today
    habits = db.scalars(
        select(Habit)
        .where(Habit.user_id == user.id, Habit.active.is_(True))
        .order_by(Habit.sort_order, Habit.id)
    ).all()
    done = set(
        db.scalars(
            select(HabitLog.habit_id).where(
                HabitLog.user_id == user.id,
                HabitLog.log_date == target,
            )
        ).all()
    )
    week_start = today - timedelta(days=today.weekday())
    week_logs = db.scalars(
        select(HabitLog).where(
            HabitLog.user_id == user.id,
            HabitLog.log_date >= week_start,
            HabitLog.log_date <= today,
        )
    ).all()
    week_counts: dict[int, int] = {}
    for log in week_logs:
        week_counts[log.habit_id] = week_counts.get(log.habit_id, 0) + 1

    return [
        {
            "id": habit.id,
            "name": habit.name,
            "icon": habit.icon,
            "done_today": habit.id in done,
            "streak": _streak(db, habit.id, today),
            "week_done": week_counts.get(habit.id, 0),
        }
        for habit in habits
    ]


@router.post("/habits", status_code=201)
def create_habit(
    payload: HabitIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    habit = Habit(user_id=user.id, name=payload.name.strip(), icon=payload.icon)
    db.add(habit)
    db.commit()
    db.refresh(habit)
    return {
        "id": habit.id,
        "name": habit.name,
        "icon": habit.icon,
        "done_today": False,
        "streak": 0,
        "week_done": 0,
    }


@router.post("/habits/{habit_id}/toggle")
def toggle_habit(
    habit_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    habit = db.scalar(
        select(Habit).where(Habit.id == habit_id, Habit.user_id == user.id)
    )
    if habit is None:
        raise HTTPException(status_code=404, detail="习惯不存在")
    today = local_date()
    log = db.scalar(
        select(HabitLog).where(
            HabitLog.habit_id == habit_id,
            HabitLog.user_id == user.id,
            HabitLog.log_date == today,
        )
    )
    if log is None:
        db.add(HabitLog(habit_id=habit_id, user_id=user.id, log_date=today))
        done = True
    else:
        db.delete(log)
        done = False
    db.commit()
    return {
        "id": habit.id,
        "name": habit.name,
        "icon": habit.icon,
        "done_today": done,
        "streak": _streak(db, habit.id, today),
        "week_done": 0,
    }


@router.delete("/habits/{habit_id}")
def delete_habit(
    habit_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    habit = db.scalar(
        select(Habit).where(Habit.id == habit_id, Habit.user_id == user.id)
    )
    if habit is None:
        raise HTTPException(status_code=404, detail="习惯不存在")
    db.execute(delete(HabitLog).where(HabitLog.habit_id == habit_id))
    db.delete(habit)
    db.commit()
    return {"deleted": habit_id}
