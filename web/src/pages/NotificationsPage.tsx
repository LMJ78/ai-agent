import { useEffect, useState } from "react";
import { Bell, CheckCheck, ChevronRight, RefreshCw } from "lucide-react";
import { api } from "../lib/api";
import type { NotificationItem, NotificationsResponse } from "../types";

type Props = {
  onOpen: (link: string) => void;
  onUnreadChange: (count: number) => void;
};

const KIND_LABEL: Record<string, string> = {
  brief: "简报",
  todo: "待办",
  event: "日程",
  habit: "习惯",
  review: "错题",
  news: "新闻"
};

function relativeTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const seconds = Math.max(1, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}

export function NotificationsPage({ onOpen, onUnreadChange }: Props) {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api<NotificationsResponse>("/api/notifications?limit=100");
      setItems(data.items);
      setUnread(data.unread);
      onUnreadChange(data.unread);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "通知加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const readAll = async () => {
    setBusy(true);
    try {
      await api("/api/notifications/read-all", { method: "POST" });
      setItems((prev) => prev.map((item) => ({ ...item, read: true })));
      setUnread(0);
      onUnreadChange(0);
    } finally {
      setBusy(false);
    }
  };

  const openItem = async (item: NotificationItem) => {
    if (!item.read) {
      try {
        await api(`/api/notifications/${item.id}/read`, { method: "POST" });
        setItems((prev) =>
          prev.map((row) => (row.id === item.id ? { ...row, read: true } : row))
        );
        const next = Math.max(0, unread - 1);
        setUnread(next);
        onUnreadChange(next);
      } catch {
        // 即使标记失败也允许跳转
      }
    }
    if (item.link) onOpen(item.link);
  };

  return (
    <div className="page notifications-page">
      <div className="page-head">
        <div>
          <h2>通知</h2>
          <p>简报、待办、日程、习惯和错题提醒都收在这里，不会再“一下过去”。</p>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={() => void load()} disabled={loading}>
            <RefreshCw size={15} /> 刷新
          </button>
          <button
            className="btn ghost"
            onClick={() => void readAll()}
            disabled={busy || unread === 0}
          >
            <CheckCheck size={15} /> 全部已读
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <div className="empty-state">正在加载通知…</div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <Bell size={28} />
          <strong>还没有通知</strong>
          <p>到点的待办、日程、习惯和错题提醒会自动出现在这里。</p>
        </div>
      ) : (
        <div className="notification-list">
          {items.map((item) => (
            <button
              key={item.id}
              className={`notification-row ${item.read ? "read" : "unread"}`}
              onClick={() => void openItem(item)}
            >
              <span className={`notification-dot ${item.read ? "read" : ""}`} />
              <span className="notification-main">
                <span className="notification-meta">
                  <span className="notification-kind">{KIND_LABEL[item.kind] || "提醒"}</span>
                  <span>{relativeTime(item.created_at)}</span>
                </span>
                <strong>{item.title}</strong>
                {item.body && <span className="notification-body">{item.body}</span>}
              </span>
              <ChevronRight size={16} className="notification-arrow" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
