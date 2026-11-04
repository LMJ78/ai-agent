"""RAG 单元测试：分词、BM25、检索工具。"""

import asyncio
import uuid

from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.init import init_db
from app.db.models import Chunk, Document, User
from app.rag.retriever import search_chunks
from app.rag.tokenizer import tokenize
from app.tools.search_notes import SearchNotesTool


def _demo_user_id() -> int:
    init_db()
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.username == "demo"))
    assert user_id is not None
    return user_id


def test_tokenizer_keeps_identifiers() -> None:
    tokens = tokenize("0-1背包的动态规划")
    assert "0-1" in tokens
    assert "背包" in tokens
    assert "动态" in tokens


def test_bm25_and_search_tool() -> None:
    user_id = _demo_user_id()
    suffix = uuid.uuid4().hex[:8]
    filename = f"w3-test-{suffix}.pptx"

    with SessionLocal() as db:
        doc = Document(
            user_id=user_id,
            course="测试课",
            chapter="ch99",
            filename=filename,
            file_path="",
            status="ready",
        )
        db.add(doc)
        db.flush()
        text = "0-1 背包问题：状态转移方程 f[i][j] = max(f[i-1][j], f[i-1][j-w[i]] + v[i])"
        db.add(
            Chunk(
                user_id=user_id,
                document_id=doc.id,
                course="测试课",
                chapter="ch99",
                filename=filename,
                location="第 1 张幻灯片",
                ordinal=0,
                text=text,
                tokens=" ".join(tokenize(text) + tokenize(filename) * 3),
                token_count=1,
            )
        )
        db.commit()
        doc_id = doc.id

    try:
        results = search_chunks(user_id, "0-1背包的状态转移方程", course="测试课", top_k=3)
        assert results
        assert results[0].filename == filename

        output = asyncio.run(
            SearchNotesTool().run(user_id, {"query": "0-1背包", "course": "测试课"})
        )
        assert "[L1]" in output
        assert "状态转移方程" in output
    finally:
        with SessionLocal() as db:
            db.execute(delete(Chunk).where(Chunk.document_id == doc_id))
            db.execute(delete(Document).where(Document.id == doc_id))
            db.commit()
