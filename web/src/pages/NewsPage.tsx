import { useEffect, useState } from "react";
import { ExternalLink, LoaderCircle, Newspaper, RefreshCw, Star } from "lucide-react";
import { ApiError, api } from "../lib/api";
import type { NewsDay, NewsResponse } from "../types";

function dayLabel(value: string): string {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const diff = Math.round((start.getTime() - date.getTime()) / 86400000);
  if (diff === 0) return "今天";
  if (diff === 1) return "昨天";
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
}

function cleanSummary(value: string): string {
  return value
    .replace(/#{1,6}\s*/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 260);
}

function publishedLabel(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export function NewsPage() {
  const [days, setDays] = useState<NewsDay[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [warning, setWarning] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api<NewsResponse>("/api/news?days=3");
      setDays(data.days);
      setWarning(data.warning || "");
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : "新闻加载失败，请稍后再试");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const patchItem = (id: number, patch: Partial<{ read: boolean; starred: boolean }>) => {
    setDays((prev) =>
      prev.map((day) => ({
        ...day,
        categories: day.categories.map((category) => ({
          ...category,
          items: category.items.map((item) => (item.id === id ? { ...item, ...patch } : item))
        }))
      }))
    );
  };

  const openItem = async (id: number) => {
    patchItem(id, { read: true });
    try {
      await api(`/api/news/${id}/read`, { method: "POST" });
    } catch {
      // 阅读状态失败不挡打开原文
    }
  };

  const toggleStar = async (id: number, starred: boolean) => {
    patchItem(id, { starred: !starred });
    await api(`/api/news/${id}/star`, {
      method: "POST",
      body: JSON.stringify({ starred: !starred })
    });
  };

  const refresh = async () => {
    setRefreshing(true);
    setError("");
    try {
      const data = await api<NewsResponse>("/api/news/refresh", { method: "POST" });
      setDays(data.days);
      setWarning(data.warning || "");
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : "刷新失败，请稍后再试");
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="page news-page">
      <div className="page-heading">
        <div>
          <h2>
            <Newspaper size={22} /> 每日新闻
          </h2>
          <p>五个方向，每天各两条；带出处链接。只保留最近 3 天。</p>
        </div>
        <button className="btn ghost" disabled={refreshing} onClick={() => void refresh()}>
          {refreshing ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />}
          {refreshing ? "正在抓取…" : "刷新今日新闻"}
        </button>
      </div>

      {warning && <div className="notice warn">{warning}</div>}
      {error && <div className="notice error">{error}</div>}

      {loading ? (
        <div className="news-loading">
          <LoaderCircle className="spin" size={20} /> 正在整理今天的新闻…
        </div>
      ) : days.length === 0 ? (
        <div className="empty-state">
          <Newspaper size={30} />
          <strong>今天还没有新闻</strong>
          <span>点右上角「刷新今日新闻」抓取一次。</span>
        </div>
      ) : (
        days.map((day) => (
          <section className="news-day" key={day.date}>
            <div className="news-date">
              <strong>{dayLabel(day.date)}</strong>
              <span>{day.date}</span>
            </div>
            <div className="news-grid">
              {day.categories.map((category) => (
                <div className="news-category" key={`${day.date}-${category.name}`}>
                  <h3>{category.name}</h3>
                  {category.items.length === 0 && (
                    <p className="news-empty">今天这个方向暂无更新</p>
                  )}
                  {category.items.map((item) => (
                    <article className={`news-item ${item.read ? "read" : ""}`} key={item.id}>
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={() => void openItem(item.id)}
                      >
                        <h4>{item.title}</h4>
                        <p>{cleanSummary(item.summary)}</p>
                      </a>
                      <div className="news-meta">
                        <span>{item.source || "网页"}</span>
                        {item.published_at && <span>{publishedLabel(item.published_at)}</span>}
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={() => void openItem(item.id)}
                        >
                          原文 <ExternalLink size={11} />
                        </a>
                        <button
                          className={`news-star ${item.starred ? "active" : ""}`}
                          title={item.starred ? "取消收藏" : "收藏"}
                          onClick={() => void toggleStar(item.id, item.starred)}
                        >
                          <Star size={12} fill={item.starred ? "currentColor" : "none"} />
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}
