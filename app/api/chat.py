"""对话接口。

W1：存消息 + 调模型 + SSE 流式。
W2：把「模型 → 工具 → 模型」的循环接进来，并把工具 trace 一并推给前端。
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

from app.agent.emotion import detect_emotion
from app.agent.llm import LLMNotConfiguredError, get_client
from app.agent.loop import run_agent
from app.agent.prompts import build_system_prompt
from app.config import settings
from app.core.deps import get_current_user
from app.db.base import SessionLocal, get_db
from app.db.models import ChatSession, Message, Question, User, utcnow
from app.services.memories import (
    format_memories_for_prompt,
    recall_memories,
    remember_explicit,
)
from app.services.usage import record_usage
from app.tools.time import format_now

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000, description="用户说的话")
    session_id: int | None = Field(default=None, description="不传则新建会话")
    mode: Literal["study", "life"] = "study"
    course: str | None = Field(default=None, max_length=64, description="学习模式下的科目")
    question_id: int | None = Field(
        default=None,
        description="已确认的题目 id；传了会把题干拼进本次提问，draft 状态会被拒绝",
    )
    teaching_stage: Literal["hint", "step", "answer"] | None = Field(
        default=None,
        description="解题阶段；不传则根据「继续 / 直接看答案」自动判断，默认只给提示",
    )
    feynman: bool = Field(
        default=False,
        description="费曼模式：用户讲、AI 追问，不直接给答案",
    )


def _sse(payload: dict[str, Any]) -> str:
    """拼一条 SSE 消息。前端按 `data: ` 逐行解析即可。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _session_course(req: ChatRequest, override: str | None = None) -> str:
    if req.mode == "life":
        return ""
    value = override if override is not None else (req.course or "")
    return value.strip()[:64]


def _resolve_teaching_stage(req: ChatRequest, has_question: bool) -> str | None:
    """题目讲解的默认节奏：先提示；「继续」下一步；「直接看答案」才给答案。"""
    if not has_question:
        return None
    if req.teaching_stage:
        return req.teaching_stage

    text = req.message.strip()
    if any(word in text for word in ("直接看答案", "看答案", "给答案", "最终答案")):
        return "answer"
    if any(word in text for word in ("继续", "下一步", "然后呢")):
        return "step"
    return "hint"


def _get_or_create_session(
    db: Session,
    user: User,
    req: ChatRequest,
    course_override: str | None = None,
) -> ChatSession:
    course = _session_course(req, course_override)
    if req.session_id is not None:
        session = db.scalar(
            select(ChatSession).where(
                ChatSession.id == req.session_id,
                ChatSession.user_id == user.id,  # 关键：只能访问自己的会话
            )
        )
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")

        # 一个会话只属于一门课，避免历史记录混在一起。
        if course and session.course and course != session.course:
            raise HTTPException(
                status_code=409,
                detail=f"这个会话属于「{session.course}」，请新建一个会话再问「{course}」",
            )
        if course and not session.course:
            session.course = course

        # 会话的模式建好就固定，避免学习/生活历史互相串。
        if session.mode != req.mode:
            current = "学习" if session.mode == "study" else "生活"
            target = "学习" if req.mode == "study" else "生活"
            raise HTTPException(
                status_code=409,
                detail=f"这个会话属于「{current}模式」，不能当成「{target}模式」继续；请新建一个{target}会话",
            )

        db.commit()
        return session

    title = req.message.strip().replace("\n", " ")[:30] or "新对话"
    session = ChatSession(user_id=user.id, title=title, mode=req.mode, course=course)
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


def _chunks(text: str, size: int = 24) -> list[str]:
    """把最终回答切成小块，沿用 W1 的 SSE 格式推给前端。

    注意：这是「接口层分块」，不是模型逐 token 流式；W2 先保证工具链路正确，
    真正的逐 token 流式留到 W5 前端一起优化。
    """
    return [text[i : i + size] for i in range(0, len(text), size)]


async def _stream_agent(
    client: Any,
    messages: list[dict[str, Any]],
    session_id: int,
    user_id: int,
    course: str = "",
) -> AsyncIterator[str]:
    final_parts: list[str] = []
    citations: list[dict[str, Any]] = []
    seen_labels: set[tuple[str, str]] = set()
    input_tokens = 0
    output_tokens = 0

    try:
        yield _sse({"session_id": session_id, "course": course})

        async for event in run_agent(client, messages, user_id, course=course):
            if event.type == "final":
                text = str(event.data.get("content", ""))
                if citations:
                    yield _sse({"type": "citations", "citations": citations})
                if text:
                    final_parts.append(text)
                    for chunk in _chunks(text):
                        yield _sse({"delta": chunk})
                yield "data: [DONE]\n\n"
                return

            if event.type == "error":
                yield _sse({"error": event.data.get("message", "未知错误")})
                yield "data: [DONE]\n\n"
                return

            if event.type == "usage":
                input_tokens += int(event.data.get("input_tokens", 0) or 0)
                output_tokens += int(event.data.get("output_tokens", 0) or 0)
                continue

            if event.type == "tool_result":
                for citation in event.data.get("citations", []) or []:
                    key = (str(citation.get("type")), str(citation.get("label")))
                    if key not in seen_labels:
                        seen_labels.add(key)
                        citations.append(citation)

            # tool_call / tool_result：单独的事件类型，前端可以显示「正在查待办…」
            yield _sse({"type": event.type, **event.data})

    except Exception as exc:  # noqa: BLE001
        logger.exception("Agent 执行失败")
        yield _sse({"error": f"Agent 执行失败：{exc}"})
        yield "data: [DONE]\n\n"

    finally:
        text = "".join(final_parts).strip()
        if text:
            try:
                with SessionLocal() as db:
                    db.add(
                        Message(
                            session_id=session_id,
                            user_id=user_id,
                            role="assistant",
                            content=text,
                            citations=json.dumps(citations, ensure_ascii=False),
                        )
                    )
                    session = db.get(ChatSession, session_id)
                    if session is not None:
                        session.updated_at = utcnow()
                    record_usage(db, user_id, input_tokens, output_tokens)
                    db.commit()
            except Exception:  # noqa: BLE001
                logger.exception("保存助手回复失败")


@router.post("/chat")
async def chat(
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    question: Question | None = None
    course_override: str | None = None

    if req.feynman and req.mode == "life":
        raise HTTPException(status_code=400, detail="费曼模式只在学习模式可用")

    if req.question_id is not None:
        question = db.scalar(
            select(Question).where(
                Question.id == req.question_id,
                Question.user_id == user.id,
            )
        )
        if question is None:
            raise HTTPException(status_code=404, detail="题目不存在")
        if question.status != "confirmed":
            raise HTTPException(
                status_code=409,
                detail="这道题还没有确认，先调用 /api/questions/{id}/confirm 再讲解",
            )
        if not question.parsed_text.strip():
            raise HTTPException(status_code=409, detail="这道题没有题干文字，请重新录入")
        if req.mode == "life":
            raise HTTPException(status_code=400, detail="题目讲解请使用 study 模式")
        if req.course and question.course and req.course.strip() != question.course:
            raise HTTPException(
                status_code=409,
                detail=f"这道题属于「{question.course}」，不能按「{req.course}」讲解",
            )
        course_override = req.course or question.course

    # 先检查 Key：没有就返回 503，别让用户看到一长串堆栈。
    try:
        client = get_client()
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    session = _get_or_create_session(db, user, req, course_override=course_override)
    history = _load_history(db, session.id, settings.history_limit)

    teaching_stage = (
        None
        if req.feynman
        else _resolve_teaching_stage(req, has_question=question is not None)
    )
    message_text = req.message.strip()
    if question is not None:
        # 题干由后端拼接，前端只传一句「请讲解这道题」即可，避免题干被截断。
        message_text = f"{message_text}\n\n【待讲题目】\n{question.parsed_text}"

    # 用户说「记住……」时先落库，后面召回就能带上；模型再调 memory 也不会重复。
    try:
        remember_explicit(db, user.id, message_text)
    except ValueError:
        pass

    memories = recall_memories(db, user.id, message_text, limit=6)
    memory_text = format_memories_for_prompt(memories)
    emotion = detect_emotion(message_text) if req.mode == "life" else None

    db.add(
        Message(
            session_id=session.id,
            user_id=user.id,
            role="user",
            content=message_text,
        )
    )
    db.commit()

    messages = [
        {
            "role": "system",
            "content": build_system_prompt(
                req.mode,
                now_text=format_now(),
                course=session.course,
                teaching_stage=teaching_stage,
                emotion=emotion,
                memories=memory_text,
                feynman=req.feynman,
            ),
        },
        *history,
        {"role": "user", "content": message_text},
    ]

    return StreamingResponse(
        _stream_agent(client, messages, session.id, user.id, session.course),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 让 Nginx 不要缓冲，否则流式会变成一次性输出
        },
    )
