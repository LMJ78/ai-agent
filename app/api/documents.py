"""课程资料上传 / 列表 / 删除。"""

import mimetypes
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.vision import VisionError, VisionNotConfiguredError
from app.core.constants import SHARED_USER_ID
from app.core.deps import get_current_user
from app.db.base import get_db
from app.db.models import Chunk, Document, User
from app.rag.ingest import delete_document, ingest_path_async, list_documents, save_upload
from app.rag.parser import ParseError

router = APIRouter()


def _pdf_preview_path(doc: Document) -> Path | None:
    """能转成 PDF 预览的文件。

    - PDF：原文件。
    - PPTX：同名 PDF（课程资料通常都会带）。
    """
    path = Path(doc.file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf" and path.is_file():
        return path

    if suffix == ".pptx":
        sibling = path.with_suffix(".pdf")
        if sibling.is_file():
            return sibling

    return None


def _preview_info(doc: Document) -> tuple[str, str]:
    """浏览器里能直接打开什么。

    - PDF / 带同名 PDF 的 PPTX：逐页图片预览。
    - MD/TXT：按文本预览。
    - 其他：提示下载。
    """
    pdf = _pdf_preview_path(doc)
    if pdf is not None:
        return "pdf", pdf.name

    path = Path(doc.file_path)
    if path.suffix.lower() in {".md", ".txt"} and path.is_file():
        return "text", doc.filename

    return "none", ""


@router.post("/documents")
async def upload_document(
    file: UploadFile = File(...),
    course: str = Form(...),
    chapter: str = Form(""),
    user: User = Depends(get_current_user),
    _db: Session = Depends(get_db),
) -> dict:
    original = Path(file.filename or "upload").name
    data = await file.read()

    saved_path: Path | None = None
    try:
        saved_path = save_upload(user.id, original, data)
        document, chunk_count = await ingest_path_async(
            user_id=user.id,
            path=saved_path,
            course=course.strip() or "未分类",
            chapter=chapter.strip(),
            original_filename=original,
        )
    except VisionNotConfiguredError as exc:
        if saved_path is not None:
            saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VisionError as exc:
        if saved_path is not None:
            saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (ValueError, ParseError) as exc:
        if saved_path is not None:
            saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        if saved_path is not None:
            saved_path.unlink(missing_ok=True)
        raise

    return {
        "id": document.id,
        "filename": document.filename,
        "course": document.course,
        "chapter": document.chapter,
        "chunks": chunk_count,
        "status": document.status,
    }


@router.get("/documents")
def get_documents(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    docs = list_documents(user.id)
    ids = [doc.id for doc in docs]
    counts: dict[int, int] = {}
    if ids:
        rows = db.execute(
            select(Chunk.document_id, func.count(Chunk.id))
            .where(Chunk.document_id.in_(ids))
            .group_by(Chunk.document_id)
        ).all()
        counts = {document_id: count for document_id, count in rows}

    result = []
    for doc in docs:
        preview_kind, preview_name = _preview_info(doc)
        result.append(
            {
                "id": doc.id,
                "filename": doc.filename,
                "course": doc.course,
                "chapter": doc.chapter,
                "status": doc.status,
                "chunks": counts.get(doc.id, 0),
                "is_shared": doc.user_id == SHARED_USER_ID,
                "preview_kind": preview_kind,
                "preview_name": preview_name,
                "created_at": doc.created_at.isoformat() if doc.created_at else "",
            }
        )
    return result


@router.get("/documents/{document_id}/preview")
def document_preview(
    document_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.user_id.in_([user.id, SHARED_USER_ID]),
        )
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="资料不存在")

    preview_kind, _ = _preview_info(doc)

    if preview_kind == "pdf":
        target = _pdf_preview_path(doc)
        assert target is not None
        return FileResponse(
            target,
            media_type="application/pdf",
            filename=target.name,
            content_disposition_type="inline",
        )

    if preview_kind == "text":
        path = Path(doc.file_path)
        return FileResponse(
            path,
            media_type="text/plain; charset=utf-8",
            filename=path.name,
            content_disposition_type="inline",
        )

    raise HTTPException(
        status_code=415,
        detail="这个格式浏览器不能直接预览。课程 PPTX 如果有配套 PDF 会自动预览；个人 PPTX/DOCX 请下载后用 WPS/Office 打开。",
    )


@router.get("/documents/{document_id}/page")
def document_page(
    document_id: int,
    page: int = Query(1, ge=1),
    width: int = Query(1400, ge=600, le=2400),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """把 PDF 的某一页渲染成 PNG，前端做翻页预览。

    比直接 iframe 原生 PDF 查看器更稳：手机宽度下能自动适配，不会被横向裁切。
    """
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.user_id.in_([user.id, SHARED_USER_ID]),
        )
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="资料不存在")

    target = _pdf_preview_path(doc)
    if target is None:
        raise HTTPException(status_code=415, detail="这份资料没有可预览的 PDF")

    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="服务器缺少 pypdfium2") from exc

    pdf = pdfium.PdfDocument(str(target))
    try:
        page_count = len(pdf)
        if page_count == 0:
            raise HTTPException(status_code=400, detail="PDF 是空的")
        if page > page_count:
            raise HTTPException(status_code=400, detail=f"页码超出范围（共 {page_count} 页）")

        pdf_page = pdf[page - 1]
        scale = width / max(1, pdf_page.get_width())
        bitmap = pdf_page.render(scale=scale)
        try:
            image = bitmap.to_pil()
            buffer = BytesIO()
            image.save(buffer, format="PNG", optimize=True)
        finally:
            bitmap.close()

        return Response(
            content=buffer.getvalue(),
            media_type="image/png",
            headers={
                "X-Page-Count": str(page_count),
                "Cache-Control": "private, max-age=3600",
            },
        )
    finally:
        pdf.close()


@router.get("/documents/{document_id}/file")
def document_file(
    document_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.user_id.in_([user.id, SHARED_USER_ID]),
        )
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="资料不存在")
    path = Path(doc.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="原文件已不存在")
    media_type = mimetypes.guess_type(doc.filename)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=doc.filename)


@router.delete("/documents/{document_id}")
def remove_document(
    document_id: int,
    user: User = Depends(get_current_user),
    _db: Session = Depends(get_db),
) -> dict:
    if not delete_document(user.id, document_id):
        raise HTTPException(status_code=404, detail="资料不存在")
    return {"deleted": document_id}
