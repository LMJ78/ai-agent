"""学习记录接口：按科目筛选、关键词搜索、回看消息、删除。"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.init import init_db
from app.db.models import ChatSession, Message, Question, User
from app.main import app


def test_session_filter_search_messages_and_delete() -> None:
    init_db()
    token = uuid.uuid4().hex[:8]
    course = f"测试科目-{token}"
    title = f"动态规划复习-{token}"

    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.username == "demo"))
        assert user_id is not None
        session = ChatSession(
            user_id=user_id,
            title=title,
            mode="study",
            course=course,
        )
        db.add(session)
        db.flush()
        session_id = session.id
        db.add_all(
            [
                Message(
                    session_id=session_id,
                    user_id=user_id,
                    role="user",
                    content=f"状态转移方程怎么推 {token}",
                ),
                Message(
                    session_id=session_id,
                    user_id=user_id,
                    role="assistant",
                    content="先定义状态，再写转移。",
                ),
            ]
        )
        db.commit()

    try:
        with TestClient(app) as client:
            listed = client.get("/api/sessions", params={"course": course})
            assert listed.status_code == 200
            assert any(item["id"] == session_id for item in listed.json())

            searched = client.get("/api/sessions", params={"q": token})
            assert searched.status_code == 200
            assert any(item["id"] == session_id for item in searched.json())

            detail = client.get(f"/api/sessions/{session_id}/messages")
            assert detail.status_code == 200
            payload = detail.json()
            assert payload["session"]["course"] == course
            assert len(payload["messages"]) == 2

            deleted = client.delete(f"/api/sessions/{session_id}")
            assert deleted.status_code == 200
    finally:
        with SessionLocal() as db:
            db.execute(delete(Message).where(Message.session_id == session_id))
            db.execute(delete(ChatSession).where(ChatSession.id == session_id))
            db.commit()

    with SessionLocal() as db:
        assert db.scalar(select(ChatSession).where(ChatSession.id == session_id)) is None
        assert db.scalar(select(Message).where(Message.session_id == session_id)) is None


def test_session_mode_filter_and_delete_keeps_question() -> None:
    """按模式筛选历史；删会话时题目留在题库，只解除 session_id。"""
    init_db()
    token = uuid.uuid4().hex[:8]
    course = f"模式测试-{token}"

    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.username == "demo"))
        assert user_id is not None
        study = ChatSession(user_id=user_id, title=f"学习-{token}", mode="study", course=course)
        life = ChatSession(user_id=user_id, title=f"生活-{token}", mode="life", course="生活")
        db.add_all([study, life])
        db.flush()
        study_id, life_id = study.id, life.id
        question = Question(
            user_id=user_id,
            session_id=study_id,
            course=course,
            original_text="这道题要保留",
            parsed_text="这道题要保留",
            status="draft",
        )
        db.add(question)
        db.commit()
        question_id = question.id

    try:
        with TestClient(app) as client:
            life_only = client.get("/api/sessions", params={"mode": "life", "limit": 200})
            assert life_only.status_code == 200
            ids = {item["id"] for item in life_only.json()}
            assert life_id in ids
            assert study_id not in ids

            deleted = client.delete(f"/api/sessions/{study_id}")
            assert deleted.status_code == 200
            assert deleted.json()["unlinked_questions"] == 1

        with SessionLocal() as db:
            kept = db.get(Question, question_id)
            assert kept is not None
            assert kept.session_id is None
            assert db.get(ChatSession, study_id) is None
    finally:
        with SessionLocal() as db:
            db.execute(delete(Question).where(Question.id == question_id))
            db.execute(delete(Message).where(Message.session_id.in_([study_id, life_id])))
            db.execute(delete(ChatSession).where(ChatSession.id.in_([study_id, life_id])))
            db.commit()
