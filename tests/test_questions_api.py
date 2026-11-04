"""题目录入接口：粘贴、文件、拍照转写、确认、列表、删除。"""

import uuid
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.api import questions as questions_module
from app.db.base import SessionLocal
from app.db.models import Question
from app.main import app


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (80, 40), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_text_question_confirm_list_and_delete() -> None:
    course = f"测试科目-{uuid.uuid4().hex[:8]}"

    with TestClient(app) as client:
        created = client.post(
            "/api/questions/text",
            json={
                "text": "0-1 背包的状态转移方程是什么？",
                "course": course,
                "chapter": "ch03",
            },
        )
        assert created.status_code == 200, created.text
        payload = created.json()
        assert payload["status"] == "draft"
        assert payload["source_type"] == "text"
        assert payload["needs_confirmation"] is True
        question_id = payload["id"]

        confirmed = client.post(
            f"/api/questions/{question_id}/confirm",
            json={"text": "0-1 背包的状态转移方程是什么？（已改错字）"},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "confirmed"
        assert "已改错字" in confirmed.json()["parsed_text"]

        listed = client.get("/api/questions", params={"course": course})
        assert listed.status_code == 200
        assert any(item["id"] == question_id for item in listed.json())

        detail = client.get(f"/api/questions/{question_id}")
        assert detail.status_code == 200
        assert detail.json()["course"] == course

        deleted = client.delete(f"/api/questions/{question_id}")
        assert deleted.status_code == 200

    with SessionLocal() as db:
        assert db.scalar(select(Question).where(Question.id == question_id)) is None


def test_upload_markdown_question() -> None:
    course = f"测试科目-{uuid.uuid4().hex[:8]}"
    content = "# 题目\n\n用动态规划求 0-1 背包的最优解，写出状态转移方程。"

    with TestClient(app) as client:
        created = client.post(
            "/api/questions/upload",
            files={"file": ("question.md", content.encode("utf-8"), "text/markdown")},
            data={"course": course, "chapter": "ch03"},
        )
        assert created.status_code == 200, created.text
        payload = created.json()
        assert payload["source_type"] == "md"
        assert "状态转移方程" in payload["parsed_text"]
        question_id = payload["id"]

        deleted = client.delete(f"/api/questions/{question_id}")
        assert deleted.status_code == 200


def test_image_question_uses_transcription(monkeypatch) -> None:
    course = f"测试科目-{uuid.uuid4().hex[:8]}"

    async def fake_transcribe(path):
        assert path.exists()
        return "1. 求 0-1 背包的最大价值。\nA. 贪心\nB. 动态规划\nC. 分治\nD. 回溯"

    monkeypatch.setattr(questions_module, "transcribe_image", fake_transcribe)

    with TestClient(app) as client:
        created = client.post(
            "/api/questions/upload",
            files={"file": ("question.png", _png_bytes(), "image/png")},
            data={"course": course},
        )
        assert created.status_code == 200, created.text
        payload = created.json()
        assert payload["source_type"] == "image"
        assert "动态规划" in payload["parsed_text"]
        assert payload["status"] == "draft"

        confirmed = client.post(
            f"/api/questions/{payload['id']}/confirm",
            json={},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "confirmed"

        deleted = client.delete(f"/api/questions/{payload['id']}")
        assert deleted.status_code == 200


def test_image_without_vision_key_returns_503(monkeypatch) -> None:
    from app.agent.vision import VisionNotConfiguredError

    async def fake_transcribe(path):
        raise VisionNotConfiguredError("还没有配置 VISION_API_KEY")

    monkeypatch.setattr(questions_module, "transcribe_image", fake_transcribe)

    with TestClient(app) as client:
        resp = client.post(
            "/api/questions/upload",
            files={"file": ("question.png", _png_bytes(), "image/png")},
            data={"course": "测试科目"},
        )
    assert resp.status_code == 503
    assert "VISION_API_KEY" in resp.json()["detail"]
