"""流式对话 + 工具调用的接口测试（用假模型，不花钱、不依赖网络）。"""

from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api import chat as chat_module
from app.config import settings
from app.db.base import SessionLocal
from app.db.models import ChatSession, Message, User
from app.main import app


def _tool_call(name: str, arguments: str, call_id: str = "call_1") -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _response(content: str | None = None, tool_calls=None) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeCompletions:
    def __init__(self, responses: list[SimpleNamespace]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[SimpleNamespace]):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def test_stream_chat_runs_tool_and_saves_reply(monkeypatch) -> None:
    fake = FakeClient(
        [
            _response(tool_calls=[_tool_call("get_current_time", "{}")]),
            _response(content="现在是下午，适合先休息一下。"),
        ]
    )
    monkeypatch.setattr(chat_module, "get_client", lambda: fake)

    with TestClient(app) as client:
        resp = client.post("/api/chat", json={"message": "现在几点了？"})

    assert resp.status_code == 200
    assert '"type": "tool_call"' in resp.text
    assert '"type": "tool_result"' in resp.text
    assert '"delta"' in resp.text
    assert "data: [DONE]" in resp.text

    with SessionLocal() as db:
        last = db.scalars(select(Message).order_by(Message.id.desc())).first()
        assert last is not None
        assert last.role == "assistant"
        assert last.content == "现在是下午，适合先休息一下。"


def test_chat_runs_web_search_tool(monkeypatch) -> None:
    """联网工具接进循环后，tool_result 会带着 [W1] 回到模型。"""
    fake = FakeClient(
        [
            _response(tool_calls=[_tool_call("web_search", '{"query": "动态规划"}')]),
            _response(content="网上资料说，动态规划的核心是拆子问题。"),
        ]
    )
    monkeypatch.setattr(chat_module, "get_client", lambda: fake)

    async def fake_search(query: str, max_results: int = 5):
        assert query == "动态规划"
        return [
            {
                "title": "动态规划入门",
                "url": "https://example.com/dp",
                "content": "把问题拆成子问题。",
            }
        ]

    monkeypatch.setattr("app.tools.web_search.search_web", fake_search)

    with TestClient(app) as client:
        resp = client.post("/api/chat", json={"message": "联网查一下动态规划"})

    assert resp.status_code == 200
    assert '"type": "tool_call"' in resp.text
    assert '"type": "tool_result"' in resp.text

    second_call = fake.chat.completions.calls[1]["messages"]
    tool_message = next(item for item in second_call if item["role"] == "tool")
    assert "[W1] 动态规划入门" in tool_message["content"]


def test_chat_rejects_mode_switch(monkeypatch) -> None:
    """学习会话不能直接切成生活模式，否则历史会串。"""
    monkeypatch.setattr(chat_module, "get_client", lambda: FakeClient([]))

    with TestClient(app) as client:
        with SessionLocal() as db:
            user_id = db.scalar(select(User.id).where(User.username == "demo"))
            assert user_id is not None
            session = ChatSession(
                user_id=user_id,
                title="模式切换测试",
                mode="study",
                course="算法设计与分析",
            )
            db.add(session)
            db.commit()
            session_id = session.id

        try:
            resp = client.post(
                "/api/chat",
                json={"message": "换成生活模式", "session_id": session_id, "mode": "life"},
            )
            assert resp.status_code == 409
            assert "学习模式" in resp.json()["detail"]
        finally:
            with SessionLocal() as db:
                db.execute(delete(ChatSession).where(ChatSession.id == session_id))
                db.commit()


def test_chat_rejects_other_users_session(monkeypatch) -> None:
    monkeypatch.setattr(chat_module, "get_client", lambda: FakeClient([]))

    with TestClient(app) as client:
        resp = client.post(
            "/api/chat",
            json={"message": "偷看别人的会话", "session_id": 999999},
        )

    assert resp.status_code == 404


def test_chat_rejects_draft_question() -> None:
    """题目没确认时，接口层直接拦住，不能拿去讲解。"""
    with TestClient(app) as client:
        created = client.post(
            "/api/questions/text",
            json={"text": "0-1 背包的状态转移方程是什么？", "course": "测试科目"},
        )
        assert created.status_code == 200
        question_id = created.json()["id"]

        resp = client.post(
            "/api/chat",
            json={"message": "请讲解这道题", "question_id": question_id},
        )
        assert resp.status_code == 409
        assert "确认" in resp.json()["detail"]

        client.delete(f"/api/questions/{question_id}")


def test_teaching_stage_defaults_to_hint_then_answer(monkeypatch) -> None:
    """默认先给提示；用户说「直接看答案」才切完整解答。"""
    fake = FakeClient(
        [
            _response(content="先想想：把大问题拆成小问题，重复的子问题在哪里？"),
            _response(content="【课程】算法\n【答案】……"),
        ]
    )
    monkeypatch.setattr(chat_module, "get_client", lambda: fake)

    with TestClient(app) as client:
        created = client.post(
            "/api/questions/text",
            json={"text": "0-1 背包的状态转移方程怎么推？", "course": "测试解题"},
        )
        assert created.status_code == 200
        question_id = created.json()["id"]
        assert client.post(f"/api/questions/{question_id}/confirm", json={}).status_code == 200

        first = client.post(
            "/api/chat",
            json={"message": "请讲解这道题", "question_id": question_id},
        )
        assert first.status_code == 200
        first_prompt = fake.chat.completions.calls[0]["messages"][0]["content"]
        assert "解题老师" in first_prompt
        assert "当前阶段：只给提示" in first_prompt
        assert "不要给完整步骤" in first_prompt

        second = client.post(
            "/api/chat",
            json={"message": "直接看答案", "question_id": question_id},
        )
        assert second.status_code == 200
        second_prompt = fake.chat.completions.calls[1]["messages"][0]["content"]
        assert "当前阶段：完整解答" in second_prompt
        assert "【答案】" in second_prompt

        client.delete(f"/api/questions/{question_id}")


def test_life_mode_injects_memory_and_emotion(monkeypatch) -> None:
    """生活模式要把长期记忆和情绪提示带进 system prompt。"""
    monkeypatch.setattr(settings, "reminder_worker_enabled", False)
    fake = FakeClient([_response(content="听起来你今天真的很累，先歇一会儿也可以。")])
    monkeypatch.setattr(chat_module, "get_client", lambda: fake)

    with TestClient(app) as client:
        memory = client.post(
            "/api/memories",
            json={"content": "我不吃香菜", "kind": "preference"},
        )
        assert memory.status_code == 200
        memory_id = memory.json()["id"]

        resp = client.post(
            "/api/chat",
            json={"message": "今天好累，也好焦虑，记得我不吃香菜", "mode": "life"},
        )
        assert resp.status_code == 200
        prompt = fake.chat.completions.calls[0]["messages"][0]["content"]
        assert "我不吃香菜" in prompt
        assert "焦虑" in prompt
        assert "先接住" in prompt
        assert "不诊断" in prompt

        client.delete(f"/api/memories/{memory_id}")


def test_chat_injects_confirmed_question(monkeypatch) -> None:
    """确认后的题会把题干拼进本次提问，模型不需要前端再传一遍。"""
    question_text = "用动态规划求 0-1 背包，写出状态转移方程。"
    fake = FakeClient([_response(content="先定义 dp[i][j]……")])
    monkeypatch.setattr(chat_module, "get_client", lambda: fake)

    with SessionLocal() as db:
        last_session_id = db.scalar(select(ChatSession.id).order_by(ChatSession.id.desc()))

    with TestClient(app) as client:
        created = client.post(
            "/api/questions/text",
            json={"text": question_text, "course": "测试科目"},
        )
        question_id = created.json()["id"]
        confirmed = client.post(f"/api/questions/{question_id}/confirm", json={})
        assert confirmed.status_code == 200

        resp = client.post(
            "/api/chat",
            json={
                "message": "请讲解这道题",
                "question_id": question_id,
                "course": "测试科目",
            },
        )

        assert resp.status_code == 200
        sent = fake.chat.completions.calls[0]["messages"][-1]["content"]
        assert "【待讲题目】" in sent
        assert question_text in sent

        client.delete(f"/api/questions/{question_id}")

    # 测试产生的会话不留在真实 data/app.db 里。
    with SessionLocal() as db:
        sessions = db.scalars(
            select(ChatSession).where(ChatSession.id > (last_session_id or 0))
        ).all()
        for session in sessions:
            db.execute(delete(Message).where(Message.session_id == session.id))
            db.delete(session)
        db.commit()
