"""课程资料上传 / 列表 / 删除 / 预览的接口测试。"""

import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter
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


def test_markdown_preview_returns_text_and_metadata() -> None:
    course = f"预览测试-{uuid.uuid4().hex[:8]}"
    content = "# 二分查找\n\n每次把区间缩小一半。"

    with TestClient(app) as client:
        uploaded = client.post(
            "/api/documents",
            files={"file": ("preview.md", content.encode("utf-8"), "text/markdown")},
            data={"course": course, "chapter": "ch99"},
        )
        assert uploaded.status_code == 200, uploaded.text
        document_id = uploaded.json()["id"]

        listed = client.get("/api/documents")
        item = next(row for row in listed.json() if row["id"] == document_id)
        assert item["preview_kind"] == "text"
        assert item["preview_name"] == "preview.md"

        preview = client.get(f"/api/documents/{document_id}/preview")
        assert preview.status_code == 200, preview.text
        assert preview.text == content
        assert "inline" in preview.headers["content-disposition"]

        client.delete(f"/api/documents/{document_id}")


def test_pptx_preview_uses_sibling_pdf(tmp_path: Path) -> None:
    pptx = tmp_path / "lesson.pptx"
    pdf = tmp_path / "lesson.pdf"
    pptx.write_bytes(b"fake pptx")
    pdf.write_bytes(b"%PDF-1.4\n% preview\n")

    with SessionLocal() as db:
        document = Document(
            user_id=0,
            course="预览测试",
            chapter="ch99",
            filename="lesson.pptx",
            file_path=str(pptx),
            status="ready",
        )
        db.add(document)
        db.commit()
        document_id = document.id

    try:
        with TestClient(app) as client:
            listed = client.get("/api/documents")
            item = next(row for row in listed.json() if row["id"] == document_id)
            assert item["preview_kind"] == "pdf"
            assert item["preview_name"] == "lesson.pdf"

            preview = client.get(f"/api/documents/{document_id}/preview")
            assert preview.status_code == 200, preview.text
            assert preview.headers["content-type"].startswith("application/pdf")
            assert preview.content.startswith(b"%PDF")
    finally:
        with SessionLocal() as db:
            db.execute(delete(Document).where(Document.id == document_id))
            db.commit()


def test_pdf_page_preview_renders_png(tmp_path: Path) -> None:
    pdf = tmp_path / "two-pages.pdf"
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=200, height=200)
    with pdf.open("wb") as file:
        writer.write(file)

    with SessionLocal() as db:
        document = Document(
            user_id=0,
            course="预览测试",
            chapter="ch99",
            filename="two-pages.pdf",
            file_path=str(pdf),
            status="ready",
        )
        db.add(document)
        db.commit()
        document_id = document.id

    try:
        with TestClient(app) as client:
            first = client.get(f"/api/documents/{document_id}/page?page=1&width=600")
            assert first.status_code == 200, first.text
            assert first.headers["content-type"] == "image/png"
            assert first.headers["x-page-count"] == "2"
            assert first.content.startswith(b"\x89PNG\r\n\x1a\n")

            out_of_range = client.get(f"/api/documents/{document_id}/page?page=3")
            assert out_of_range.status_code == 400
    finally:
        with SessionLocal() as db:
            db.execute(delete(Document).where(Document.id == document_id))
            db.commit()
