"""每日新闻：内部页面用，按用户缓存最近 3 天，不再推送到手机。"""

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.timeutil import local_date, now_utc
from app.db.models import NewsItem
from app.tools.base import ToolError
from app.tools.web_search import search_web

RETENTION_DAYS = 3

# 页面固定五个方向，每个方向两条；不推送，只在 Agent 内查看。
NEWS_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("科技/AI", "人工智能 科技 最新新闻"),
    ("国内", "中国 国内 今日重要新闻"),
    ("国际", "国际 今日重要新闻"),
    ("财经", "财经 今日重要新闻"),
    ("体育", "体育 今日重要新闻"),
)


def purge_old_news(db: Session, user_id: int, *, today: date | None = None) -> int:
    """只保留今天和前两天，返回删除条数。"""
    current = today or local_date()
    cutoff = current - timedelta(days=RETENTION_DAYS - 1)
    result = db.execute(
        delete(NewsItem).where(
            NewsItem.user_id == user_id,
            NewsItem.news_date < cutoff,
        )
    )
    db.commit()
    return int(result.rowcount or 0)


def purge_all_old_news(today: date | None = None) -> int:
    """后台清理所有用户超过 3 天的新闻，不依赖有人打开页面。"""
    from app.db.base import SessionLocal

    current = today or local_date()
    cutoff = current - timedelta(days=RETENTION_DAYS - 1)
    with SessionLocal() as db:
        result = db.execute(delete(NewsItem).where(NewsItem.news_date < cutoff))
        db.commit()
        return int(result.rowcount or 0)


def _parse_published(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _source_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _clean(text: object, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value[:limit]


async def refresh_news(
    db: Session,
    user_id: int,
    *,
    force: bool = False,
) -> int:
    """抓取今日新闻并入库；force=True 时重建今天的数据。

    返回新增条数。没有 Key、网络失败且一条都没拿到时抛 ToolError。
    """
    today = local_date()
    purge_old_news(db, user_id, today=today)

    if not force:
        exists = db.scalar(
            select(NewsItem.id)
            .where(NewsItem.user_id == user_id, NewsItem.news_date == today)
            .limit(1)
        )
        if exists is not None:
            return 0
    else:
        db.execute(
            delete(NewsItem).where(
                NewsItem.user_id == user_id, NewsItem.news_date == today
            )
        )
        db.commit()

    added = 0
    seen: set[str] = set()
    errors: list[ToolError] = []
    fetched_at = now_utc()

    for category, query in NEWS_CATEGORIES:
        try:
            results = await search_web(query, 2, topic="news", days=2)
        except ToolError as exc:
            errors.append(exc)
            continue

        for result in results:
            title = _clean(result.get("title"), 500)
            url = str(result.get("url") or "").strip()[:1000]
            if not title or not url or url in seen:
                continue
            seen.add(url)
            db.add(
                NewsItem(
                    user_id=user_id,
                    news_date=today,
                    category=category,
                    title=title,
                    summary=_clean(result.get("content"), 800),
                    url=url,
                    source=_source_from_url(url),
                    published_at=_parse_published(result.get("published_date")),
                    fetched_at=fetched_at,
                )
            )
            added += 1
        db.commit()

    if added == 0 and errors:
        raise errors[0]
    return added


def list_news(db: Session, user_id: int, *, days: int = RETENTION_DAYS) -> list[dict]:
    """按日期分组返回最近 N 天新闻，日期从新到旧。"""
    days = max(1, min(days, RETENTION_DAYS))
    today = local_date()
    purge_old_news(db, user_id, today=today)
    cutoff = today - timedelta(days=days - 1)
    rows = db.scalars(
        select(NewsItem)
        .where(
            NewsItem.user_id == user_id,
            NewsItem.news_date >= cutoff,
        )
        .order_by(NewsItem.news_date.desc(), NewsItem.id.asc())
    ).all()

    by_date: dict[date, dict[str, list[dict]]] = {}
    for item in rows:
        by_date.setdefault(item.news_date, {}).setdefault(item.category, []).append(
            {
                "id": item.id,
                "title": item.title,
                "summary": item.summary,
                "url": item.url,
                "source": item.source,
                "published_at": item.published_at.isoformat()
                if item.published_at
                else "",
            }
        )

    response = []
    for day in sorted(by_date, reverse=True):
        categories = [
            {"name": category, "items": by_date[day].get(category, [])}
            for category, _ in NEWS_CATEGORIES
            if by_date[day].get(category)
        ]
        response.append({"date": day.isoformat(), "categories": categories})
    return response
