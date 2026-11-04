"""L3 自测接口：出题、提交判分、历史、删除。"""

import json
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api import quizzes as quizzes_module
from app.db.base import SessionLocal
from app.db.init import init_db
from app.db.models import Chunk, Document, Quiz, QuizQuestion, User
from app.main import app
from app.rag.tokenizer import tokenize


class FakeCompletions:
    def __init__(self, content: str):
        self.content = content
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeClient:
    def __init__(self, content: str):
        self.chat = SimpleNamespace(completions=FakeCompletions(content))


def _seed_chunk(course: str, chapter: str, filename: str, text: str) -> tuple[int, int]:
    init_db()
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.username == "demo"))
        assert user_id is not None
        document = Document(
            user_id=user_id,
            course=course,
            chapter=chapter,
            filename=filename,
            file_path="",
            status="ready",
        )
        db.add(document)
        db.flush()
        db.add(
            Chunk(
                user_id=user_id,
                document_id=document.id,
                course=course,
                chapter=chapter,
                filename=filename,
                location="第 1 张幻灯片",
                ordinal=0,
                text=text,
                tokens=" ".join(tokenize(text) + tokenize(filename) * 3),
                token_count=1,
            )
        )
        db.commit()
        return document.id, user_id


def test_generate_submit_and_delete_quiz(monkeypatch) -> None:
    token = uuid.uuid4().hex[:8]
    course = f"测试科目-{token}"
    chapter = "ch03"
    filename = f"动态规划-{token}.pptx"
    document_id, _ = _seed_chunk(
        course,
        chapter,
        filename,
        "0-1 背包问题用动态规划求解，状态转移方程 f[i][j] = max(f[i-1][j], f[i-1][j-w[i]] + v[i])。",
    )

    generated = [
        {
            "question": "0-1 背包问题通常用哪种算法求解？",
            "options": ["A. 贪心", "B. 动态规划", "C. 分治", "D. 回溯"],
            "answer": "B",
            "explanation": "0-1 背包具有最优子结构，常用动态规划。",
        },
        {
            "question": "状态转移方程中 f[i][j] 表示什么？",
            "options": ["A. 前 i 个物品、容量 j 的最优值", "B. 第 i 个物品的价值", "C. 背包容量", "D. 物品重量"],
            "answer": "A",
            "explanation": "f[i][j] 表示前 i 个物品在容量 j 下的最大价值。",
        },
    ]
    fake = FakeClient(json.dumps(generated, ensure_ascii=False))
    monkeypatch.setattr(quizzes_module, "get_client", lambda: fake)

    quiz_id = None
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/quizzes/generate",
                json={
                    "course": course,
                    "chapter": chapter,
                    "topic": "0-1背包",
                    "count": 2,
                },
            )
            assert resp.status_code == 200, resp.text
            payload = resp.json()
            quiz_id = payload["id"]
            assert payload["count"] == 2
            assert all("answer" not in item for item in payload["items"])
            assert fake.chat.completions.calls

            items = payload["items"]
            submitted = client.post(
                f"/api/quizzes/{quiz_id}/submit",
                json={"answers": {str(items[0]["id"]): "B", str(items[1]["id"]): "A"}},
            )
            assert submitted.status_code == 200, submitted.text
            result = submitted.json()
            assert result["score"] == 2
            assert result["percent"] == 100.0
            assert all(item["is_correct"] for item in result["items"])
            assert result["items"][0]["correct_answer"] == "B"

            fetched = client.get(f"/api/quizzes/{quiz_id}")
            assert fetched.status_code == 200
            assert all("answer" not in item for item in fetched.json()["items"])

            listed = client.get("/api/quizzes", params={"course": course})
            assert listed.status_code == 200
            assert any(item["id"] == quiz_id for item in listed.json())

            deleted = client.delete(f"/api/quizzes/{quiz_id}")
            assert deleted.status_code == 200
            quiz_id = None
    finally:
        if quiz_id is not None:
            with SessionLocal() as db:
                db.execute(delete(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id))
                db.execute(delete(Quiz).where(Quiz.id == quiz_id))
                db.commit()
        with SessionLocal() as db:
            db.execute(delete(Chunk).where(Chunk.document_id == document_id))
            db.execute(delete(Document).where(Document.id == document_id))
            db.commit()
