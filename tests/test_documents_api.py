"""课程资料上传 / 列表 / 删除的接口测试。"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.models import Chunk, Document
from app.main import app


def test_upload_markdown_list_and_delete() -> None:
    course = f"测试课-{uuid.uuid4().hex[:8]}"
    content = "# 动态规划\n\n0-1 背包的状态转移方程是 f[i][j] = max(f[i-1][j], f[i-1][j-w[i]] + v[i])。"

    with TestClient(app) as client:
        resp = client.post(
            "/api/documents",
            files={"file": ("w3-note.md", content.encode("utf-8"), "text/markdown")},
            data={"course": course, "chapter": "ch99"},
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["chunks"] >= 1
        document_id = payload["id"]

        listed = client.get("/api/documents")
        assert listed.status_code == 200
        assert any(item["id"] == document_id for item in listed.json())

        deleted = client.delete(f"/api/documents/{document_id}")
        assert deleted.status_code == 200

    with SessionLocal() as db:
        assert db.scalar(select(Document).where(Document.id == document_id)) is None
        assert db.scalar(select(Chunk).where(Chunk.document_id == document_id)) is None
