"""把课件写入 documents / chunks：解析、分词、落库。"""

from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select

from app.config import DATA_DIR
from app.core.constants import SHARED_USER_ID
from app.db.base import SessionLocal
from app.db.models import Chunk, Document
from app.rag.parser import ParseError, ParsedChunk, parse_file, parse_file_async
from app.rag.tokenizer import tokenize

UPLOAD_DIR = DATA_DIR / "uploads"
ALLOWED_SUFFIXES = {".pdf", ".docx", ".pptx", ".md", ".txt"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def save_upload(user_id: int, filename: str, data: bytes) -> Path:
    """把上传文件按用户分目录存，文件名用随机串，避免路径穿越。"""
    original = Path(filename or "upload").name
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"不支持的文件类型：{suffix or '未知'}；支持 PDF/DOCX/PPTX/MD/TXT")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("文件超过 20MB，先压缩或拆分后再传")

    target_dir = UPLOAD_DIR / str(user_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid4().hex}{suffix}"
    target.write_bytes(data)
    return target


def ingest_path(
    user_id: int,
    path: Path,
    course: str,
    chapter: str = "",
    original_filename: str | None = None,
) -> tuple[Document, int]:
    """同步解析并入库（文字版课件/测试用）。"""
    return _store_parsed(
        user_id=user_id,
        path=path,
        course=course,
        chapter=chapter,
        original_filename=original_filename,
        parsed=parse_file(path),
    )


async def ingest_path_async(
    user_id: int,
    path: Path,
    course: str,
    chapter: str = "",
    original_filename: str | None = None,
) -> tuple[Document, int]:
    """上传接口用：扫描版 PDF 会逐页 OCR，不阻塞事件循环。"""
    return _store_parsed(
        user_id=user_id,
        path=path,
        course=course,
        chapter=chapter,
        original_filename=original_filename,
        parsed=await parse_file_async(path),
    )


def _store_parsed(
    user_id: int,
    path: Path,
    course: str,
    chapter: str,
    original_filename: str | None,
    parsed: list[ParsedChunk],
) -> tuple[Document, int]:
    if not parsed:
        raise ParseError("没有解析出可用的文字")

    with SessionLocal() as db:
        document = Document(
            user_id=user_id,
            course=(course or "未分类")[:64],
            chapter=(chapter or "")[:64],
            filename=(original_filename or path.name)[:255],
            file_path=str(path)[:512],
            status="ready",
        )
        db.add(document)
        db.flush()  # 先拿到 document.id

        chunk_count = 0
        for ordinal, piece in enumerate(parsed):
            # 文件名/章节重复几次，相当于给「标题命中」加权：
            # 问「0-1 背包」时，文件名里带这个词的课件会排得更靠前。
            tokens = (
                tokenize(piece.text)
                + tokenize(document.filename) * 3
                + tokenize(document.chapter) * 2
            )
            db.add(
                Chunk(
                    user_id=user_id,
                    document_id=document.id,
                    course=document.course,
                    chapter=document.chapter,
                    filename=document.filename,
                    location=piece.location,
                    ordinal=ordinal,
                    text=piece.text,
                    tokens=" ".join(tokens),
                    token_count=len(tokens),
                )
            )
            chunk_count += 1

        db.commit()
        db.refresh(document)
        return document, chunk_count


def list_documents(user_id: int, *, include_shared: bool = True) -> list[Document]:
    """列出个人资料；默认同时返回所有学生共用的课程资料。"""
    with SessionLocal() as db:
        owners = [user_id, SHARED_USER_ID] if include_shared else [user_id]
        return list(
            db.scalars(
                select(Document)
                .where(Document.user_id.in_(owners))
                .order_by(Document.id.desc())
            ).all()
        )


def delete_document(user_id: int, document_id: int) -> bool:
    with SessionLocal() as db:
        document = db.scalar(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
        if document is None:
            return False

        db.execute(delete(Chunk).where(Chunk.document_id == document.id))
        file_path = Path(document.file_path)
        db.delete(document)
        db.commit()

    # 只删除上传目录里的副本；批量导入的原始课件不要动。
    try:
        if file_path.is_relative_to(UPLOAD_DIR.resolve()):
            file_path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass
    return True
