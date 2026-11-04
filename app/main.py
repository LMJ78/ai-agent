"""FastAPI 入口。

启动方式（在 ai-agent 目录下）：
    uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.questions import router as questions_router
from app.api.quizzes import router as quizzes_router
from app.api.sessions import router as sessions_router
from app.config import settings
from app.db.base import get_db
from app.db.init import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 应用启动时建表、准备 demo 用户；只执行一次。
    init_db()
    logging.getLogger(__name__).info("数据库就绪，服务启动")
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="学习助手 + 生活伴侣 AI Agent（第 3 周：本地 RAG）",
    lifespan=lifespan,
)

app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(documents_router, prefix="/api", tags=["documents"])
app.include_router(sessions_router, prefix="/api", tags=["sessions"])
app.include_router(questions_router, prefix="/api", tags=["questions"])
app.include_router(quizzes_router, prefix="/api", tags=["quizzes"])


@app.get("/health", tags=["system"])
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """健康检查：能查到数据库才算真的健康。"""
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "model": settings.deepseek_model,
    }


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": "/health",
        "chat": "POST /api/chat",
    }
