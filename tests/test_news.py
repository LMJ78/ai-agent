"""每日新闻：内部缓存、3 天保留、API。"""

import asyncio
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import settings
from app.core.timeutil import local_date
from app.db.base import SessionLocal
from app.db.init import DEMO_USERNAME
from app.db.models import NewsItem, User
from app.main import app
from app.services import news as news_service
from app.services.briefs import build_morning_brief, get_or_create_settings


def _user_id() -> int:
    with SessionLocal() as db:
        value = db.scalar(select(User.id).where(User.username == DEMO_USERNAME))
    assert value is not None
    return value


def _cleanup() -> None:
    with SessionLocal() as db:
        db.execute(delete(NewsItem).where(NewsItem.title.like("W7新闻-%")))
        db.commit()


async def _fake_search(query, max_results=5, *, client=None, topic=None, days=None):
    assert topic == "news"
    assert days == 2
    return [
        {
            "title": f"W7新闻-{query}-{index}",
            "url": f"https://example.com/{abs(hash(query))}/{index}",
            "content": f"这是 {query} 的第 {index} 条摘要。",
            "published_date": "2026-11-10T10:00:00Z",
        }
        for index in range(1, max_results + 1)
    ]


def test_news_refresh_groups_five_categories_and_retains_three_days(monkeypatch) -> None:
    _cleanup()
    monkeypatch.setattr(news_service, "search_web", _fake_search)
    user_id = _user_id()
    today = local_date()

    with SessionLocal() as db:
        db.add(
            NewsItem(
                user_id=user_id,
                news_date=today - timedelta(days=3),
                category="旧闻",
                title="W7新闻-过期",
                summary="应该被清掉",
                url="https://example.com/old",
                source="example.com",
            )
        )
        db.commit()

    with TestClient(app) as client:
        refreshed = client.post("/api/news/refresh")
        assert refreshed.status_code == 200, refreshed.text
        payload = refreshed.json()
        assert payload["retention_days"] == 3
        assert len(payload["days"]) == 1
        assert [c["name"] for c in payload["days"][0]["categories"]] == [
            "科技/AI",
            "国内",
            "国际",
            "财经",
            "体育",
        ]
        assert all(len(c["items"]) == 2 for c in payload["days"][0]["categories"])

        loaded = client.get("/api/news?days=3")
        assert loaded.status_code == 200
        assert loaded.json()["days"] == payload["days"]

    with SessionLocal() as db:
        assert db.scalar(
            select(NewsItem).where(NewsItem.title == "W7新闻-过期")
        ) is None
        remaining = db.scalars(
            select(NewsItem).where(NewsItem.user_id == user_id)
        ).all()
        assert remaining
        assert all(item.news_date >= today - timedelta(days=2) for item in remaining)


def test_purge_all_old_news_removes_expired_rows() -> None:
    _cleanup()
    user_id = _user_id()
    today = local_date()
    with SessionLocal() as db:
        db.add(
            NewsItem(
                user_id=user_id,
                news_date=today - timedelta(days=3),
                category="旧闻",
                title="W7新闻-后台过期",
                summary="应该被后台清掉",
                url="https://example.com/old-all",
                source="example.com",
            )
        )
        db.commit()

    assert news_service.purge_all_old_news(today) >= 1
    with SessionLocal() as db:
        assert db.scalar(
            select(NewsItem).where(NewsItem.title == "W7新闻-后台过期")
        ) is None


def test_news_without_key_returns_actionable_503(monkeypatch) -> None:
    _cleanup()
    monkeypatch.setattr(settings, "tavily_api_key", "")
    with TestClient(app) as client:
        response = client.post("/api/news/refresh")
        assert response.status_code == 503
        assert "TAVILY_API_KEY" in response.json()["detail"]


def test_morning_brief_does_not_include_news() -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == DEMO_USERNAME))
        assert user is not None
        cfg = get_or_create_settings(db, user.id)
        cfg.news_topics = "AI, 算法"
        db.commit()
        try:
            _, content = asyncio.run(build_morning_brief(db, user, cfg))
        finally:
            cfg.news_topics = ""
            db.commit()
    assert "新闻" not in content
    assert "[W" not in content
