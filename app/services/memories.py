"""长期记忆：存一条事实、按相关度召回、格式化进提示词。

W4 先做「用户明确说记住」和「模型判断值得记」两类，不做全自动抽取。
这样误记少，也方便用户查看和删除。
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Memory
from app.rag.tokenizer import tokenize

KIND_LABELS = {
    "identity": "身份",
    "preference": "偏好",
    "plan": "计划",
    "relationship": "关系",
    "other": "其他",
}
VALID_KINDS = set(KIND_LABELS)


def normalize_kind(kind: str | None) -> str:
    value = (kind or "other").strip().lower()
    return value if value in VALID_KINDS else "other"


def clean_content(content: str, limit: int = 500) -> str:
    """压掉多余空白，避免一条记忆占满上下文。"""
    return re.sub(r"\s+", " ", str(content)).strip()[:limit]


def add_memory(
    db: Session, user_id: int, content: str, kind: str = "other"
) -> tuple[Memory, bool]:
    """新增一条记忆；完全重复的内容不重复存。返回 (记录, 是否新建)。"""
    text = clean_content(content)
    if not text:
        raise ValueError("记忆内容不能为空")

    kind = normalize_kind(kind)
    exists = db.scalar(
        select(Memory).where(
            Memory.user_id == user_id,
            func.lower(Memory.content) == text.lower(),
        )
    )
    if exists is not None:
        return exists, False

    memory = Memory(user_id=user_id, kind=kind, content=text)
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory, True


def list_memories(
    db: Session, user_id: int, kind: str | None = None, limit: int = 50
) -> list[Memory]:
    stmt = select(Memory).where(Memory.user_id == user_id)
    if kind:
        stmt = stmt.where(Memory.kind == normalize_kind(kind))
    return list(
        db.scalars(stmt.order_by(Memory.created_at.desc(), Memory.id.desc()).limit(limit)).all()
    )


def delete_memory(db: Session, user_id: int, memory_id: int) -> bool:
    memory = db.scalar(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    )
    if memory is None:
        return False
    db.delete(memory)
    db.commit()
    return True


def _score(query: str, content: str) -> float:
    """轻量相关度：词重叠 + 整句子串命中。够小规模用，不引入向量库。"""
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return 1.0 if query and query in content else 0.0

    content_tokens = set(tokenize(content))
    overlap = len(query_tokens & content_tokens)
    if overlap == 0 and query not in content:
        return 0.0

    score = overlap / (len(query_tokens) ** 0.5)
    if query and query in content:
        score += 1.0
    return score


def recall_memories(
    db: Session, user_id: int, query: str, limit: int = 6
) -> list[Memory]:
    """按当前这句话召回最相关的记忆；没有相关词时返回最近几条。"""
    rows = list_memories(db, user_id, limit=100)
    if not rows:
        return []

    scored = [(memory, _score(query, memory.content)) for memory in rows]
    related = [(memory, score) for memory, score in scored if score > 0]
    if related:
        related.sort(key=lambda item: (item[1], item[0].created_at), reverse=True)
        return [memory for memory, _ in related[:limit]]
    return rows[:limit]


def format_memory(memory: Memory) -> str:
    return f"[{KIND_LABELS.get(memory.kind, '其他')}] {memory.content}"


def format_memories_for_prompt(memories: list[Memory]) -> str:
    if not memories:
        return ""
    lines = "\n".join(f"- {format_memory(memory)}" for memory in memories)
    return (
        "关于这个用户，之前记住的信息：\n"
        f"{lines}\n"
        "只在相关时自然使用；不要生硬复述，也不要把这些信息说给别的用户。"
    )


_EXPLICIT_MEMORY = re.compile(
    r"(?:请)?(?:帮我)?(?:记住|记一下|别忘了)[：:，,\s]*(.+)", re.S
)


def infer_kind(content: str) -> str:
    if any(word in content for word in ("喜欢", "不喜欢", "爱吃", "不吃", "习惯", "讨厌")):
        return "preference"
    if any(word in content for word in ("我是", "我叫", "专业", "年级", "生日")):
        return "identity"
    if any(word in content for word in ("考试", "计划", "打算", "要交", "截止", "周")):
        return "plan"
    if any(word in content for word in ("朋友", "室友", "家人", "对象", "同学")):
        return "relationship"
    return "other"


def remember_explicit(db: Session, user_id: int, text: str) -> Memory | None:
    """兜底抽取「记住……」这种明确指令，避免模型漏调 memory 工具。"""
    match = _EXPLICIT_MEMORY.search(text or "")
    if match is None:
        return None
    content = clean_content(match.group(1), limit=300)
    if len(content) < 2:
        return None
    memory, _ = add_memory(db, user_id, content, infer_kind(content))
    return memory
