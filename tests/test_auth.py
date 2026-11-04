"""注册、登录与真实 JWT 鉴权。"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.deps import get_current_user
from app.db.base import SessionLocal
from app.db.models import (
    ChatSession,
    InviteCode,
    Memory,
    PushChannel,
    Question,
    Quiz,
    QuizQuestion,
    Todo,
    User,
    utcnow,
)
from app.main import app


def _invite(uses: int = 1) -> str:
    code = f"TEST-{uuid4().hex[:8].upper()}"
    with SessionLocal() as db:
        db.add(InviteCode(code=code, max_uses=uses))
        db.commit()
    return code


def _register(client: TestClient, username: str, password: str = "password123") -> dict:
    code = _invite()
    resp = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": password,
            "display_name": username,
            "invite_code": code,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _cleanup(*usernames: str) -> None:
    with SessionLocal() as db:
        ids = db.scalars(select(User.id).where(User.username.in_(usernames))).all()
        if ids:
            db.execute(delete(Question).where(Question.user_id.in_(ids)))
            db.execute(delete(QuizQuestion).where(QuizQuestion.user_id.in_(ids)))
            db.execute(delete(Quiz).where(Quiz.user_id.in_(ids)))
            db.execute(delete(Todo).where(Todo.user_id.in_(ids)))
            db.execute(delete(Memory).where(Memory.user_id.in_(ids)))
            db.execute(delete(PushChannel).where(PushChannel.user_id.in_(ids)))
            db.execute(delete(ChatSession).where(ChatSession.user_id.in_(ids)))
            db.execute(delete(User).where(User.id.in_(ids)))
            db.commit()


def test_register_requires_valid_invite() -> None:
    with TestClient(app) as client:
        bad = client.post(
            "/api/auth/register",
            json={
                "username": f"u{uuid4().hex[:8]}",
                "password": "password123",
                "invite_code": "NOT-A-CODE",
            },
        )
        assert bad.status_code == 400
        assert "邀请码" in bad.json()["detail"]


def test_register_login_and_me() -> None:
    username = f"u{uuid4().hex[:8]}"
    try:
        with TestClient(app) as client:
            data = _register(client, username)
            token = data["access_token"]
            assert data["user"]["username"] == username

            app.dependency_overrides.pop(get_current_user, None)
            me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert me.status_code == 200
            assert me.json()["username"] == username

            login = client.post(
                "/api/auth/login",
                json={"username": username, "password": "password123"},
            )
            assert login.status_code == 200
            assert login.json()["access_token"]

            wrong = client.post(
                "/api/auth/login",
                json={"username": username, "password": "wrong-password"},
            )
            assert wrong.status_code == 401
    finally:
        _cleanup(username)


def test_invite_is_single_use() -> None:
    code = _invite(uses=1)
    usernames = [f"u{uuid4().hex[:8]}", f"u{uuid4().hex[:8]}"]
    try:
        with TestClient(app) as client:
            first = client.post(
                "/api/auth/register",
                json={
                    "username": usernames[0],
                    "password": "password123",
                    "invite_code": code,
                },
            )
            assert first.status_code == 201
            second = client.post(
                "/api/auth/register",
                json={
                    "username": usernames[1],
                    "password": "password123",
                    "invite_code": code,
                },
            )
            assert second.status_code == 400
            assert "用完" in second.json()["detail"]
    finally:
        _cleanup(*usernames)


def test_business_api_rejects_missing_token() -> None:
    app.dependency_overrides.pop(get_current_user, None)
    with TestClient(app) as client:
        resp = client.get("/api/sessions")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_user_cannot_read_other_users_session() -> None:
    user_a = f"u{uuid4().hex[:8]}"
    user_b = f"u{uuid4().hex[:8]}"
    try:
        with TestClient(app) as client:
            token_a = _register(client, user_a, "password123")["access_token"]
            _register(client, user_b, "password123")
            with SessionLocal() as db:
                a = db.scalar(select(User).where(User.username == user_a))
                session = ChatSession(user_id=a.id, title="A 的会话", course="算法设计与分析")
                db.add(session)
                db.commit()
                session_id = session.id

            # 用 B 的 token 访问 A 的会话；不调用模型，接口层应直接 404。
            app.dependency_overrides.pop(get_current_user, None)
            token_b = client.post(
                "/api/auth/login",
                json={"username": user_b, "password": "password123"},
            ).json()["access_token"]
            resp_b = client.post(
                "/api/chat",
                json={"message": "偷看", "session_id": session_id},
                headers={"Authorization": f"Bearer {token_b}"},
            )
            assert resp_b.status_code == 404
    finally:
        _cleanup(user_a, user_b)


def test_user_cannot_read_other_users_question() -> None:
    user_a = f"u{uuid4().hex[:8]}"
    user_b = f"u{uuid4().hex[:8]}"
    try:
        with TestClient(app) as client:
            _register(client, user_a)
            _register(client, user_b)
            with SessionLocal() as db:
                a = db.scalar(select(User).where(User.username == user_a))
                q = Question(
                    user_id=a.id,
                    course="算法设计与分析",
                    parsed_text="测试题干",
                    source_type="text",
                    status="confirmed",
                    confirmed_at=utcnow(),
                )
                db.add(q)
                db.commit()
                question_id = q.id

            app.dependency_overrides.pop(get_current_user, None)
            token_b = client.post(
                "/api/auth/login",
                json={"username": user_b, "password": "password123"},
            ).json()["access_token"]
            headers = {"Authorization": f"Bearer {token_b}"}

            detail = client.get(f"/api/questions/{question_id}", headers=headers)
            assert detail.status_code == 404

            chat = client.post(
                "/api/chat",
                json={"message": "讲讲这道题", "question_id": question_id},
                headers=headers,
            )
            assert chat.status_code == 404
    finally:
        _cleanup(user_a, user_b)


def test_invite_expiry() -> None:
    code = f"EXP-{uuid4().hex[:8].upper()}"
    with SessionLocal() as db:
        db.add(
            InviteCode(
                code=code,
                max_uses=1,
                expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
        db.commit()
    username = f"u{uuid4().hex[:8]}"
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/auth/register",
                json={
                    "username": username,
                    "password": "password123",
                    "invite_code": code,
                },
            )
            assert resp.status_code == 400
            assert "过期" in resp.json()["detail"]
    finally:
        _cleanup(username)
