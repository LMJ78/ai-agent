"""题目录入：粘贴文字、上传 PDF/PPTX/Word、拍照转写，确认后再讲解。

流程刻意分成两步：
1. 创建草稿（draft）——解析/转写，返回给用户看；
2. 用户确认（confirm）——可以顺手改错字，再进入讲题。
这样拍照识别错了不会直接拿去讲，避免“一本正经地讲错题”。
"""

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.vision import VisionError, VisionNotConfiguredError, transcribe_image
from app.config import DATA_DIR
from app.core.deps import get_current_user
from app.db.base import get_db
from app.db.models import ChatSession, Question, User, utcnow
from app.rag.parser import ParseError, parse_file

router = APIRouter()

QUESTION_DIR = DATA_DIR / "uploads" / "questions"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
DOC_SUFFIXES = {".pdf", ".pptx", ".docx", ".md", ".txt"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_DOC_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 12000


class TextQuestionIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    course: str = Field(default="未分类", max_length=64)
    chapter: str = Field(default="", max_length=64)
    session_id: int | None = None


class QuestionConfirmIn(BaseModel):
    # 用户确认时可以改错字；不传就沿用转写结果
    text: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)


def _truncate(text: str) -> str:
    text = text.strip()
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return text[:MAX_TEXT_CHARS] + "\n\n…（题目过长，后续内容已截断）"


def _question_dict(question: Question) -> dict:
    return {
        "id": question.id,
        "session_id": question.session_id,
        "course": question.course,
        "chapter": question.chapter,
        "source_type": question.source_type,
        "original_text": question.original_text,
        "parsed_text": question.parsed_text,
        # 前端确认卡片用它显示原图；只返回自己的题，不泄露别人路径。
        "source_path": question.source_path,
        "status": question.status,
        "needs_confirmation": question.status != "confirmed",
        "created_at": question.created_at.isoformat() if question.created_at else "",
        "confirmed_at": question.confirmed_at.isoformat() if question.confirmed_at else "",
    }


def _get_session(db: Session, user_id: int, session_id: int | None) -> ChatSession | None:
    if session_id is None:
        return None
    session = db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
        )
    )
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


def _resolve_course(course: str, session: ChatSession | None) -> str:
    value = (course or "").strip() or "未分类"
    if session is not None and session.course:
        # 从某个科目的会话里录题，默认跟随会话；显式换科目则拒绝，避免串科。
        if value in {"未分类", ""}:
            return session.course[:64]
        if value != session.course:
            raise HTTPException(
                status_code=409,
                detail=f"这个会话属于「{session.course}」，不能录成「{value}」；请新建会话",
            )
    return value[:64]


def _save_file(user_id: int, filename: str, data: bytes, allowed: set[str], limit: int) -> Path:
    original = Path(filename or "upload").name
    suffix = Path(original).suffix.lower()
    if suffix not in allowed:
        raise ValueError(f"不支持的文件类型：{suffix or '未知'}")
    if not data:
        raise ValueError("文件是空的")
    if len(data) > limit:
        raise ValueError(f"文件超过 {limit // (1024 * 1024)}MB，请压缩或拆分后再传")

    target_dir = QUESTION_DIR / str(user_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid4().hex}{suffix}"
    target.write_bytes(data)
    return target


def _create(
    db: Session,
    *,
    user_id: int,
    session_id: int | None,
    course: str,
    chapter: str,
    source_type: str,
    original_text: str,
    parsed_text: str,
    source_path: str = "",
) -> Question:
    question = Question(
        user_id=user_id,
        session_id=session_id,
        course=course,
        chapter=(chapter or "").strip()[:64],
        source_type=source_type,
        original_text=_truncate(original_text),
        parsed_text=_truncate(parsed_text),
        source_path=source_path[:512],
        status="draft",
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


def _get_own(db: Session, user_id: int, question_id: int) -> Question:
    question = db.scalar(
        select(Question).where(Question.id == question_id, Question.user_id == user_id)
    )
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    return question


@router.post("/questions/text")
def create_text_question(
    payload: TextQuestionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="题目不能为空")

    session = _get_session(db, user.id, payload.session_id)
    course = _resolve_course(payload.course, session)
    question = _create(
        db,
        user_id=user.id,
        session_id=session.id if session else None,
        course=course,
        chapter=payload.chapter,
        source_type="text",
        original_text=text,
        parsed_text=text,
    )
    return _question_dict(question)


@router.post("/questions/upload")
async def upload_question(
    file: UploadFile = File(...),
    course: str = Form("未分类"),
    chapter: str = Form(""),
    session_id: int | None = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    original = Path(file.filename or "upload").name
    suffix = Path(original).suffix.lower()
    if suffix not in IMAGE_SUFFIXES | DOC_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="题目支持图片（JPG/PNG/WebP）、PDF、PPTX、DOCX、MD、TXT",
        )

    data = await file.read()
    is_image = suffix in IMAGE_SUFFIXES
    saved_path: Path | None = None
    try:
        saved_path = _save_file(
            user.id,
            original,
            data,
            IMAGE_SUFFIXES if is_image else DOC_SUFFIXES,
            MAX_IMAGE_BYTES if is_image else MAX_DOC_BYTES,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session = _get_session(db, user.id, session_id)
    course_value = _resolve_course(course, session)

    try:
        if is_image:
            parsed_text = await transcribe_image(saved_path)
            source_type = "image"
            original_text = ""
        else:
            pieces = parse_file(saved_path)
            parsed_text = "\n\n".join(piece.text for piece in pieces)
            source_type = suffix.lstrip(".")
            original_text = ""
    except VisionNotConfiguredError as exc:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VisionError as exc:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (ParseError, ValueError) as exc:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        saved_path.unlink(missing_ok=True)
        raise

    question = _create(
        db,
        user_id=user.id,
        session_id=session.id if session else None,
        course=course_value,
        chapter=chapter,
        source_type=source_type,
        original_text=original_text,
        parsed_text=parsed_text,
        source_path=str(saved_path),
    )
    return _question_dict(question)


@router.get("/questions")
def list_questions(
    course: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(Question).where(Question.user_id == user.id)
    if course:
        stmt = stmt.where(Question.course == course)
    if status:
        stmt = stmt.where(Question.status == status)
    rows = db.scalars(stmt.order_by(Question.id.desc()).limit(limit)).all()
    return [_question_dict(item) for item in rows]


@router.get("/questions/{question_id}")
def get_question(
    question_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _question_dict(_get_own(db, user.id, question_id))


@router.post("/questions/{question_id}/confirm")
def confirm_question(
    question_id: int,
    payload: QuestionConfirmIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    question = _get_own(db, user.id, question_id)

    if payload.text is not None:
        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="确认后的题目不能为空")
        question.parsed_text = _truncate(text)

    if not question.parsed_text.strip():
        raise HTTPException(status_code=400, detail="还没有可确认的题目文字，请重新上传")

    question.status = "confirmed"
    question.confirmed_at = utcnow()
    db.commit()
    db.refresh(question)
    return _question_dict(question)


@router.delete("/questions/{question_id}")
def delete_question(
    question_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    question = _get_own(db, user.id, question_id)
    source_path = question.source_path
    db.delete(question)
    db.commit()

    # 只删题目上传目录里的副本，不碰课程资料目录。
    try:
        path = Path(source_path)
        if source_path and path.is_relative_to(QUESTION_DIR.resolve()):
            path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass
    return {"deleted": question_id}
