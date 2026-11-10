"""BM25 检索：不依赖向量库，先把本地 RAG 跑起来。

数据量很小（61 份课件、约一两千个 chunk），每次查询全量打分足够快。
以后要换向量检索，只需要替换 search_chunks 的实现，工具和接口不用动。
"""

from collections import Counter
from dataclasses import dataclass
import math

from sqlalchemy import select

from app.core.constants import SHARED_USER_ID
from app.db.base import SessionLocal
from app.db.models import Chunk
from app.rag.tokenizer import tokenize


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    text: str
    filename: str
    course: str
    chapter: str
    location: str
    score: float


def search_chunks(
    user_id: int,
    query: str,
    course: str | None = None,
    chapter: str | None = None,
    top_k: int = 4,
) -> list[RetrievedChunk]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    with SessionLocal() as db:
        # 个人上传的资料 + 公共课程资料都能检索。
        stmt = select(Chunk).where(Chunk.user_id.in_([user_id, SHARED_USER_ID]))
        if course:
            stmt = stmt.where(Chunk.course == course)
        if chapter:
            stmt = stmt.where(Chunk.chapter == chapter)
        rows = db.scalars(stmt).all()

    if not rows:
        return []

    docs: list[tuple[Chunk, list[str]]] = []
    for row in rows:
        tokens = row.tokens.split()
        if tokens:
            docs.append((row, tokens))

    if not docs:
        return []

    total = len(docs)
    avg_len = sum(len(tokens) for _, tokens in docs) / total
    query_set = set(query_tokens)

    # 文档频率：只统计查询词，没必要给整个词表建索引。
    df: Counter[str] = Counter()
    for _, tokens in docs:
        token_set = set(tokens)
        for term in query_set:
            if term in token_set:
                df[term] += 1

    k1, b = 1.5, 0.75
    scored: list[tuple[float, Chunk]] = []
    for row, tokens in docs:
        length = len(tokens)
        tf = Counter(tokens)
        score = 0.0
        for term in query_set:
            freq = tf.get(term, 0)
            if not freq:
                continue
            idf = math.log(1 + (total - df[term] + 0.5) / (df[term] + 0.5))
            denom = freq + k1 * (1 - b + b * length / avg_len)
            score += idf * freq * (k1 + 1) / denom

        # 标题命中额外加分：问「0-1 背包」时，文件名里带这四个字的课件应该更靠前。
        name_hits = len(query_set & set(tokenize(row.filename)))
        score += name_hits * 5.0

        if score > 0:
            scored.append((score, row))

    scored.sort(key=lambda item: (-item[0], item[1].id))
    return [
        RetrievedChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            text=row.text,
            filename=row.filename,
            course=row.course,
            chapter=row.chapter,
            location=row.location,
            score=round(score, 4),
        )
        for score, row in scored[: max(1, min(top_k, 10))]
    ]
