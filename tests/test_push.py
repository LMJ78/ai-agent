"""PushPlus 配置、测试发送、适配器错误处理。"""

import asyncio
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import settings
from app.db.base import SessionLocal
from app.db.init import init_db
from app.db.models import PushChannel, User
from app.main import app
from app.services.push import (
    PushError,
    PushNotConfiguredError,
    mask_token,
    send_pushplus,
)


def _demo_user_id() -> int:
    init_db()
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.username == "demo"))
    assert user_id is not None
    return user_id


def test_push_channel_api_and_test_send(monkeypatch) -> None:
    monkeypatch.setattr(settings, "reminder_worker_enabled", False)
    user_id = _demo_user_id()

    with SessionLocal() as db:
        db.execute(delete(PushChannel).where(PushChannel.user_id == user_id))
        db.commit()

    try:
        with TestClient(app) as client:
            empty = client.get("/api/push/channel").json()
            assert empty["configured"] is False

            saved = client.put(
                "/api/push/channel",
                json={"token": "test-token-1234", "enabled": True},
            )
            assert saved.status_code == 200
            body = saved.json()
            assert body["configured"] is True
            assert body["token_masked"] == "test****1234"
            assert "test-token-1234" not in str(body)

            assert client.delete("/api/push/channel").status_code == 200
            assert client.post("/api/push/test").status_code == 400

            # 重新配置，再用假发送验证测试接口。
            assert client.put(
                "/api/push/channel",
                json={"token": "test-token-1234", "enabled": True},
            ).status_code == 200

            async def fake_send(*args, **kwargs):
                return {"code": 200}

            monkeypatch.setattr("app.api.push.send_to_user", fake_send)
            sent = client.post("/api/push/test")
            assert sent.status_code == 200
            assert sent.json()["ok"] is True

            assert client.delete("/api/push/channel").status_code == 200
    finally:
        with SessionLocal() as db:
            db.execute(delete(PushChannel).where(PushChannel.user_id == user_id))
            db.commit()


def test_mask_token() -> None:
    assert mask_token("") == ""
    assert mask_token("12345678") == "****"
    assert mask_token("abcdefghij") == "abcd****ghij"


def test_send_pushplus_success_and_business_error() -> None:
    async def success() -> dict:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = __import__("json").loads(request.content)
            assert payload["token"] == "tvly-test"
            assert payload["template"] == "txt"
            return httpx.Response(200, json={"code": 200, "msg": "请求成功"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await send_pushplus("tvly-test", "标题", "内容", client=client)

    data = asyncio.run(success())
    assert data["code"] == 200

    async def failure() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 500, "msg": "token 无效"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await send_pushplus("bad-token", "标题", "内容", client=client)

    with pytest.raises(PushError, match="token 无效"):
        asyncio.run(failure())

    with pytest.raises(PushNotConfiguredError):
        asyncio.run(send_pushplus("", "标题", "内容"))


def test_pushplus_api_does_not_accept_empty_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "reminder_worker_enabled", False)
    with TestClient(app) as client:
        resp = client.put("/api/push/channel", json={"token": "", "enabled": True})
    assert resp.status_code == 422
