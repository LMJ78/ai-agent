"""待办面板接口（供 W5 的 Streamlit 使用）。

工具调用和这里共用同一张 todos 表；所有查询都带 user_id。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.base import get_db
from app.db.models import Todo, User
from app.tools.todo import _in_period, _parse_due_at, _parse_remind_at

router = APIRouter()


class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    due_at: str | None = Field(default=None, description="ISO 时间，如 2026-11-06 23:59")
    remind_at: str | None = Field(default=None, description="ISO 时间；不填则用截止时间")


class TodoUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    due_at: str | None = None
    remind_at: str | None = None
    done: bool | None = None


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _todo_dict(todo: Todo) -> dict:
    return {
        "id": todo.id,
        "title": todo.title,
        "due_at": _iso(todo.due_at),
        "remind_at": _iso(todo.remind_at),
        "reminded_at": _iso(todo.reminded_at),
        "done": todo.done,
        "created_at": _iso(todo.created_at),
    }


def _own(db: Session, user_id: int, todo_id: int) -> Todo:
    todo = db.scalar(select(Todo).where(Todo.id == todo_id, Todo.user_id == user_id))
    if todo is None:
        raise HTTPException(status_code=404, detail="待办不存在")
    return todo


@router.get("/todos")
def list_todos(
    status: str = Query(default="pending", pattern="^(pending|done|all)$"),
    period: str = Query(default="all", pattern="^(today|week|all)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    stmt = select(Todo).where(Todo.user_id == user.id)
    if status == "pending":
        stmt = stmt.where(Todo.done.is_(False))
    elif status == "done":
        stmt = stmt.where(Todo.done.is_(True))

    rows = db.scalars(
        stmt.order_by(Todo.done, Todo.due_at.is_(None), Todo.due_at, Todo.id.desc()).limit(200)
    ).all()
    return [_todo_dict(todo) for todo in rows if _in_period(todo, period)]


@router.post("/todos", status_code=201)
def create_todo(
    payload: TodoCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        todo = Todo(
            user_id=user.id,
            title=payload.title.strip()[:255],
            due_at=_parse_due_at(payload.due_at),
            remind_at=_parse_remind_at(payload.remind_at),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return _todo_dict(todo)


@router.patch("/todos/{todo_id}")
def update_todo(
    todo_id: int,
    payload: TodoUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    todo = _own(db, user.id, todo_id)
    try:
        if payload.title is not None:
            todo.title = payload.title.strip()[:255]
        if payload.due_at is not None:
            todo.due_at = _parse_due_at(payload.due_at)
            todo.reminded_at = None
            todo.remind_attempts = 0
        if payload.remind_at is not None:
            todo.remind_at = _parse_remind_at(payload.remind_at)
            todo.reminded_at = None
            todo.remind_attempts = 0
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.done is not None:
        todo.done = payload.done
    db.commit()
    db.refresh(todo)
    return _todo_dict(todo)


@router.delete("/todos/{todo_id}")
def delete_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    todo = _own(db, user.id, todo_id)
    db.delete(todo)
    db.commit()
    return {"deleted": todo_id}
