"""测试：第 1 周先保证「服务能起来」和「没 Key 时给友好提示」。"""

from fastapi.testclient import TestClient

from app.api import chat as chat_module
from app.agent.llm import get_client
from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_chat_returns_503_without_api_key(monkeypatch) -> None:
    # 确保测试不受本机 .env 影响
    monkeypatch.setattr(chat_module.settings, "deepseek_api_key", "")
    get_client.cache_clear()

    with TestClient(app) as client:
        resp = client.post("/api/chat", json={"message": "你好"})

    assert resp.status_code == 503
    assert "DEEPSEEK_API_KEY" in resp.json()["detail"]
