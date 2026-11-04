"""课件解析：PDF / PPTX / DOCX / Markdown / TXT → 带位置的文本块。"""

from dataclasses import dataclass
from pathlib import Path
import re

from docx import Document as DocxDocument
from pypdf import PdfReader
from pptx import Presentation


class ParseError(Exception):
    """文件能读，但抽不出可用文字（比如扫描版 PDF）。"""


@dataclass
class ParsedChunk:
    text: str
    location: str


def split_text(text: str, size: int = 600, overlap: int = 80) -> list[str]:
    """按字符切块，尽量在换行处断开，块之间留一点重叠。"""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # 在块的后 40% 里找最后一个换行，避免把一句话切成两半。
            cut = text.rfind("\n", start + int(size * 0.6), end)
            if cut > start:
                end = cut
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return pieces


def _parse_pptx(path: Path) -> list[ParsedChunk]:
    prs = Presentation(str(path))
    chunks: list[ParsedChunk] = []

    for index, slide in enumerate(prs.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                text = shape.text_frame.text.strip()
                if text:
                    parts.append(text)
            if getattr(shape, "has_table", False):
                rows = []
                for row in shape.table.rows:
                    cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    if any(cells):
                        rows.append(" | ".join(cells))
                if rows:
                    parts.append("\n".join(rows))

        try:
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    parts.append(f"[备注] {notes}")
        except Exception:  # noqa: BLE001 - 备注缺失不影响正文
            pass

        text = "\n".join(parts).strip()
        for piece in split_text(text):
            chunks.append(ParsedChunk(piece, f"第 {index} 张幻灯片"))

    if not chunks:
        raise ParseError("PPTX 里没有抽到文字，可能是纯图片课件")
    return chunks


def _parse_pdf(path: Path) -> list[ParsedChunk]:
    reader = PdfReader(str(path))
    chunks: list[ParsedChunk] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for piece in split_text(text):
            chunks.append(ParsedChunk(piece, f"第 {index} 页"))
    if not chunks:
        raise ParseError("PDF 没有文字层，可能是扫描版；请转成文字版或截图走拍照识别")
    return chunks


def _parse_docx(path: Path) -> list[ParsedChunk]:
    doc = DocxDocument(str(path))
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    text = "\n".join(parts)
    chunks = [ParsedChunk(piece, "正文") for piece in split_text(text)]
    if not chunks:
        raise ParseError("DOCX 里没有抽到文字")
    return chunks


def _parse_text(path: Path) -> list[ParsedChunk]:
    text = path.read_text(encoding="utf-8", errors="replace")
    chunks = [ParsedChunk(piece, "正文") for piece in split_text(text)]
    if not chunks:
        raise ParseError("文件是空的")
    return chunks


def parse_file(path: Path) -> list[ParsedChunk]:
    suffix = path.suffix.lower()
    if suffix == ".pptx":
        return _parse_pptx(path)
    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix == ".docx":
        return _parse_docx(path)
    if suffix in {".md", ".txt"}:
        return _parse_text(path)
    raise ParseError(f"不支持的文件类型：{suffix}")
