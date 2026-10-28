"""流式对话的单元测试：用假模型替身，不花钱、不依赖网络。"""

from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import chat as chat_module
from app.db.base import SessionLocal
from app.db.models import Message
from app.main import app


class FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks
        self._iter = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeCompletions:
    async def create(self, **_kwargs):
        return FakeStream(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="你好"))]
                ),
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="，同学"))]
                ),
            ]
        )


class FakeClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions())


def test_stream_chat_returns_sse_and_saves_reply(monkeypatch) -> None:
    monkeypatch.setattr(chat_module, "get_client", lambda: FakeClient())

    with TestClient(app) as client:
        resp = client.post("/api/chat", json={"message": "打个招呼"})

    assert resp.status_code == 200
    assert '"delta": "你好"' in resp.text
    assert '"delta": "，同学"' in resp.text
    assert "data: [DONE]" in resp.text

    with SessionLocal() as db:
        last = db.scalars(select(Message).order_by(Message.id.desc())).first()
        assert last is not None
        assert last.role == "assistant"
        assert last.content == "你好，同学"


def test_chat_rejects_other_users_session(monkeypatch) -> None:
    monkeypatch.setattr(chat_module, "get_client", lambda: FakeClient())

    with TestClient(app) as client:
        resp = client.post(
            "/api/chat",
            json={"message": "偷看别人的会话", "session_id": 999999},
        )

    assert resp.status_code == 404
