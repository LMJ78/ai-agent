"""L3 考前自测：按科目/章节从本地课件出选择题，提交后判分。

出题只使用检索到的课件片段，避免模型凭空编题；
提交前不返回答案，提交后才给正确答案和解释。
"""

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.agent.llm import LLMNotConfiguredError, get_client
from app.config import settings
from app.core.deps import get_current_user
from app.db.base import get_db
from app.db.models import Quiz, QuizQuestion, User
from app.rag.retriever import search_chunks
from app.services.review import record_wrong_answer

router = APIRouter()

MAX_QUESTIONS = 10


class QuizGenerateIn(BaseModel):
    course: str = Field(min_length=1, max_length=64)
    chapter: str = Field(default="", max_length=64)
    topic: str = Field(default="", max_length=200)
    count: int = Field(default=5, ge=1, le=MAX_QUESTIONS)


class QuizSubmitIn(BaseModel):
    # key 是题目 id，value 是 "A"/"B"/"C"/"D"
    answers: dict[int, str] = Field(default_factory=dict)


def _extract_array(text: str) -> list:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start, end = text.find("["), text.rfind("]")
    if start >= 0 and end > start:
        data = json.loads(text[start : end + 1])
        return data if isinstance(data, list) else []

    # 有些模型会包一层 {"questions": [...]}，兼容一下。
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        data = json.loads(text[start : end + 1])
        if isinstance(data, dict):
            for key in ("questions", "items", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
    return []


def _normalize_choice(value: object) -> str:
    text = str(value or "").strip().upper()
    match = re.match(r"^[A-D]", text)
    return match.group(0) if match else ""


def _valid_items(raw: list) -> list[dict]:
    items: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question") or "").strip()
        options = entry.get("options")
        answer = _normalize_choice(entry.get("answer"))
        if not question or not isinstance(options, list) or len(options) != 4 or not answer:
            continue
        cleaned = [str(option).strip() for option in options]
        if any(not option for option in cleaned):
            continue
        items.append(
            {
                "question": question,
                "options": cleaned,
                "answer": answer,
                "explanation": str(entry.get("explanation") or "").strip(),
            }
        )
    return items


def _own_quiz(db: Session, user_id: int, quiz_id: int) -> Quiz:
    quiz = db.scalar(select(Quiz).where(Quiz.id == quiz_id, Quiz.user_id == user_id))
    if quiz is None:
        raise HTTPException(status_code=404, detail="自测不存在")
    return quiz


def _load_items(db: Session, quiz_id: int) -> list[QuizQuestion]:
    return list(
        db.scalars(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_id == quiz_id)
            .order_by(QuizQuestion.ordinal.asc())
        ).all()
    )


def _item_dict(item: QuizQuestion, reveal: bool = False) -> dict:
    data = {
        "id": item.id,
        "ordinal": item.ordinal,
        "kind": item.kind,
        "question": item.question,
        "options": json.loads(item.options or "[]"),
        "source": item.source,
    }
    if reveal:
        data["answer"] = item.answer
        data["explanation"] = item.explanation
    return data


def _quiz_dict(quiz: Quiz, items: list[QuizQuestion], reveal: bool = False) -> dict:
    return {
        "id": quiz.id,
        "course": quiz.course,
        "chapter": quiz.chapter,
        "status": quiz.status,
        "count": len(items),
        "created_at": quiz.created_at.isoformat() if quiz.created_at else "",
        "items": [_item_dict(item, reveal=reveal) for item in items],
    }


@router.post("/quizzes/generate")
async def generate_quiz(
    payload: QuizGenerateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    course = payload.course.strip()
    chapter = payload.chapter.strip()
    query = payload.topic.strip() or chapter or course
    chunks = search_chunks(
        user.id,
        query,
        course=course,
        chapter=chapter or None,
        top_k=8,
    )
    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="这门课还没有可用的课件片段，先在 /api/documents 上传资料",
        )

    context = "\n\n".join(
        f"[L{index}] {chunk.filename} {chunk.location}\n{chunk.text[:800]}"
        for index, chunk in enumerate(chunks, start=1)
    )
    prompt = f"""你是大学算法课老师，正在出一套 L3 考前自测题。
请只根据下面课件片段出 {payload.count} 道单项选择题，不要出编程题，不要编造片段里没有的知识点。

课件片段：
{context}

只输出 JSON 数组，每项格式：
{{"question": "题干", "options": ["A. ...", "B. ...", "C. ...", "D. ..."], "answer": "A", "explanation": "为什么"}}
要求：
1. 每题四个选项，只有一个正确；
2. answer 只写 A/B/C/D；
3. explanation 用一两句话说明依据；
4. 不要输出 JSON 以外的任何文字。"""

    try:
        client = get_client()
        response = await client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "system", "content": "你只输出合法 JSON，不聊天。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=2500,
        )
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"出题模型调用失败：{exc}") from exc

    content = response.choices[0].message.content or ""
    try:
        raw_items = _extract_array(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="模型返回的题目不是合法 JSON，请重试") from exc

    items = _valid_items(raw_items)
    if not items:
        raise HTTPException(status_code=502, detail="模型没有生成有效题目，请重试或换一个章节")

    quiz = Quiz(user_id=user.id, course=course[:64], chapter=chapter[:64])
    db.add(quiz)
    db.flush()
    for ordinal, item in enumerate(items):
        source = ""
        if ordinal < len(chunks):
            source = f"{chunks[ordinal].filename} {chunks[ordinal].location}"[:255]
        db.add(
            QuizQuestion(
                quiz_id=quiz.id,
                user_id=user.id,
                ordinal=ordinal,
                kind="choice",
                question=item["question"],
                options=json.dumps(item["options"], ensure_ascii=False),
                answer=item["answer"],
                explanation=item["explanation"],
                source=source,
            )
        )
    db.commit()
    db.refresh(quiz)

    return _quiz_dict(quiz, _load_items(db, quiz.id), reveal=False)


@router.get("/quizzes")
def list_quizzes(
    course: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(Quiz).where(Quiz.user_id == user.id)
    if course:
        stmt = stmt.where(Quiz.course == course)
    quizzes = db.scalars(stmt.order_by(Quiz.id.desc()).limit(limit)).all()

    counts = {}
    if quizzes:
        rows = db.execute(
            select(QuizQuestion.quiz_id, func.count(QuizQuestion.id))
            .where(QuizQuestion.quiz_id.in_([quiz.id for quiz in quizzes]))
            .group_by(QuizQuestion.quiz_id)
        ).all()
        counts = {quiz_id: count for quiz_id, count in rows}

    return [
        {
            "id": quiz.id,
            "course": quiz.course,
            "chapter": quiz.chapter,
            "status": quiz.status,
            "count": counts.get(quiz.id, 0),
            "created_at": quiz.created_at.isoformat() if quiz.created_at else "",
        }
        for quiz in quizzes
    ]


@router.get("/quizzes/{quiz_id}")
def get_quiz(
    quiz_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    quiz = _own_quiz(db, user.id, quiz_id)
    return _quiz_dict(quiz, _load_items(db, quiz_id), reveal=False)


@router.post("/quizzes/{quiz_id}/submit")
def submit_quiz(
    quiz_id: int,
    payload: QuizSubmitIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    quiz = _own_quiz(db, user.id, quiz_id)
    items = _load_items(db, quiz_id)
    if not items:
        raise HTTPException(status_code=400, detail="这套自测没有题目")

    correct = 0
    details = []
    wrong_added = 0
    for item in items:
        given = _normalize_choice(payload.answers.get(item.id, ""))
        is_correct = given == item.answer
        if is_correct:
            correct += 1
        else:
            record_wrong_answer(
                db, user_id=user.id, quiz=quiz, item=item, given=given
            )
            wrong_added += 1
        details.append(
            {
                **_item_dict(item, reveal=True),
                "your_answer": given,
                "correct_answer": item.answer,
                "is_correct": is_correct,
            }
        )

    quiz.status = "submitted"
    db.commit()
    db.refresh(quiz)
    return {
        "quiz_id": quiz.id,
        "course": quiz.course,
        "score": correct,
        "total": len(items),
        "percent": round(correct / len(items) * 100, 1),
        "wrong_added": wrong_added,
        "items": details,
    }


@router.delete("/quizzes/{quiz_id}")
def delete_quiz(
    quiz_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    quiz = _own_quiz(db, user.id, quiz_id)
    db.execute(delete(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id))
    db.delete(quiz)
    db.commit()
    return {"deleted": quiz_id}
