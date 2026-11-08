"""课程资料上传 / 列表 / 删除。"""

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.vision import VisionError, VisionNotConfiguredError
from app.core.deps import get_current_user
from app.db.base import get_db
from app.db.models import Chunk, User
from app.rag.ingest import delete_document, ingest_path_async, list_documents, save_upload
from app.rag.parser import ParseError

router = APIRouter()


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
            .where(Chunk.document_id.in_(ids), Chunk.user_id == user.id)
            .group_by(Chunk.document_id)
        ).all()
        counts = {document_id: count for document_id, count in rows}

    return [
        {
            "id": doc.id,
            "filename": doc.filename,
            "course": doc.course,
            "chapter": doc.chapter,
            "status": doc.status,
            "chunks": counts.get(doc.id, 0),
            "created_at": doc.created_at.isoformat() if doc.created_at else "",
        }
        for doc in docs
    ]


@router.delete("/documents/{document_id}")
def remove_document(
    document_id: int,
    user: User = Depends(get_current_user),
    _db: Session = Depends(get_db),
) -> dict:
    if not delete_document(user.id, document_id):
        raise HTTPException(status_code=404, detail="资料不存在")
    return {"deleted": document_id}
