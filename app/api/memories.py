"""长期记忆的查看与删除接口。"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.base import get_db
from app.db.models import Memory, User
from app.services.memories import (
    add_memory,
    delete_memory,
    list_memories,
    normalize_kind,
    recall_memories,
)

router = APIRouter()


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=500)
    kind: str = "other"


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    content: str
    created_at: datetime


def _out(memory: Memory) -> MemoryOut:
    return MemoryOut.model_validate(memory)


@router.get("/memories", response_model=list[MemoryOut])
def get_memories(
    kind: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if q and q.strip():
        rows = recall_memories(db, user.id, q.strip(), limit=limit)
    else:
        rows = list_memories(db, user.id, kind=kind, limit=limit)
    return [_out(memory) for memory in rows]


@router.post("/memories", response_model=MemoryOut)
def create_memory(
    payload: MemoryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        memory, _ = add_memory(db, user.id, payload.content, normalize_kind(payload.kind))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(memory)


@router.delete("/memories/{memory_id}")
def remove_memory(
    memory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not delete_memory(db, user.id, memory_id):
        raise HTTPException(status_code=404, detail="没有找到这条记忆")
    return {"ok": True}
