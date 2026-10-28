"""对话接口。

第 1 周只做两件事：
1. 把消息存进数据库（含 user_id）；
2. 调模型，用 SSE 流式把回答推回去。
还没有工具调用，第 2 周才加。
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.llm import LLMNotConfiguredError, get_client
from app.agent.prompts import build_system_prompt
from app.config import settings
from app.core.deps import get_current_user
from app.db.base import SessionLocal, get_db
from app.db.models import ChatSession, Message, User, utcnow

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000, description="用户说的话")
    session_id: int | None = Field(default=None, description="不传则新建会话")
    mode: Literal["study", "life"] = "study"


def _sse(payload: dict[str, Any]) -> str:
    """拼一条 SSE 消息。前端按 `data: ` 逐行解析即可。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _get_or_create_session(db: Session, user: User, req: ChatRequest) -> ChatSession:
    if req.session_id is not None:
        session = db.scalar(
            select(ChatSession).where(
                ChatSession.id == req.session_id,
                ChatSession.user_id == user.id,  # 关键：只能访问自己的会话
            )
        )
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.mode != req.mode:
            session.mode = req.mode
            db.commit()
        return session

    title = req.message.strip().replace("\n", " ")[:30] or "新对话"
    session = ChatSession(user_id=user.id, title=title, mode=req.mode)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _load_history(db: Session, session_id: int, limit: int) -> list[dict[str, str]]:
    """取最近 limit 条消息，按时间正序返回。"""
    rows = db.scalars(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


async def _stream_reply(
    client: Any,
    messages: list[dict[str, str]],
    session_id: int,
    user_id: int,
) -> AsyncIterator[str]:
    parts: list[str] = []

    try:
        stream = await client.chat.completions.create(
            model=settings.deepseek_model,
            messages=messages,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            stream=True,
        )

        # 第一帧先告诉前端 session_id，方便它记住这轮对话属于哪个会话。
        yield _sse({"session_id": session_id})

        async for chunk in stream:
            # 有些 chunk 的 choices 为空（例如用量帧），直接跳过。
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                parts.append(delta)
                yield _sse({"delta": delta})

        yield "data: [DONE]\n\n"

    except Exception as exc:  # noqa: BLE001 - 这里要把错误变成前端能看懂的提示
        logger.exception("模型调用失败")
        yield _sse({"error": f"模型调用失败：{exc}"})
        yield "data: [DONE]\n\n"

    finally:
        # 流结束后再落库：即使客户端中途断开，已经生成的部分也会保存。
        text = "".join(parts).strip()
        if text:
            try:
                with SessionLocal() as db:
                    db.add(
                        Message(
                            session_id=session_id,
                            user_id=user_id,
                            role="assistant",
                            content=text,
                        )
                    )
                    session = db.get(ChatSession, session_id)
                    if session is not None:
                        session.updated_at = utcnow()
                    db.commit()
            except Exception:  # noqa: BLE001
                logger.exception("保存助手回复失败")


@router.post("/chat")
async def chat(
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    # 先检查 Key：没有就返回 503，别让用户看到一长串堆栈。
    try:
        client = get_client()
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    session = _get_or_create_session(db, user, req)
    history = _load_history(db, session.id, settings.history_limit)

    db.add(
        Message(
            session_id=session.id,
            user_id=user.id,
            role="user",
            content=req.message,
        )
    )
    db.commit()

    messages = [
        {"role": "system", "content": build_system_prompt(req.mode)},
        *history,
        {"role": "user", "content": req.message},
    ]

    return StreamingResponse(
        _stream_reply(client, messages, session.id, user.id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 让 Nginx 不要缓冲，否则流式会变成一次性输出
        },
    )
