"""扫描版 PDF 的 OCR 管线测试：不调用真实视觉模型。"""

import asyncio

from pypdf import PdfWriter

from app.config import settings
from app.rag import parser as parser_module


def _blank_pdf(path, pages: int = 1) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    with path.open("wb") as file:
        writer.write(file)


def test_scanned_pdf_uses_vision_ocr(monkeypatch, tmp_path) -> None:
    path = tmp_path / "scanned.pdf"
    _blank_pdf(path)
    prompts: list[str] = []

    async def fake_transcribe(image_path, prompt=""):
        prompts.append(prompt)
        assert image_path.exists()
        return "动态规划的基本思想是把问题拆成重叠子问题。"

    monkeypatch.setattr(parser_module, "transcribe_image", fake_transcribe)
    monkeypatch.setattr(settings, "vision_ocr_max_pages", 5)

    chunks = asyncio.run(parser_module.parse_file_async(path))

    assert chunks
    assert chunks[0].location == "第 1 页"
    assert "动态规划" in chunks[0].text
    assert prompts and "OCR" in prompts[0]


def test_scanned_pdf_over_page_limit_is_readable(monkeypatch, tmp_path) -> None:
    path = tmp_path / "big-scanned.pdf"
    _blank_pdf(path, pages=2)
    monkeypatch.setattr(settings, "vision_ocr_max_pages", 1)

    try:
        asyncio.run(parser_module.parse_file_async(path))
    except parser_module.ParseError as exc:
        assert "超过 OCR 上限" in str(exc)
    else:
        raise AssertionError("超过页数上限时应该报 ParseError")
