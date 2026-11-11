import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CalendarDays, Clock3, LoaderCircle, MapPin, Plus, Trash2, Upload } from "lucide-react";
import { ApiError, api } from "../lib/api";
import type { CalendarConflict, CalendarEvent } from "../types";

function localInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatWhen(value: string): string {
  const date = new Date(value);
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export function CalendarPage() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [conflicts, setConflicts] = useState<CalendarConflict[]>([]);
  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState("");
  const [location, setLocation] = useState("");
  const [startAt, setStartAt] = useState(() => {
    const date = new Date(Date.now() + 60 * 60 * 1000);
    date.setMinutes(0, 0, 0);
    return localInput(date);
  });
  const [weekly, setWeekly] = useState(false);
  const [saving, setSaving] = useState(false);
  const [importingImage, setImportingImage] = useState(false);
  const [importMsg, setImportMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const imageRef = useRef<HTMLInputElement>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [rows, clashes] = await Promise.all([
        api<CalendarEvent[]>("/api/calendar/events?days=30"),
        api<CalendarConflict[]>("/api/calendar/conflicts?days=30").catch(() => [])
      ]);
      setEvents(rows);
      setConflicts(clashes);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const add = async () => {
    if (!title.trim() || !startAt) return;
    setSaving(true);
    try {
      await api<CalendarEvent>("/api/calendar/events", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          location: location.trim(),
          start_at: new Date(startAt).toISOString(),
          recurrence: weekly ? "weekly" : "none"
        })
      });
      setTitle("");
      setLocation("");
      await load();
    } finally {
      setSaving(false);
    }
  };

  const importIcs = async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const result = await api<{ imported: number }>("/api/calendar/import", {
      method: "POST",
      body: form
    });
    setImportMsg(`已从 .ics 导入 ${result.imported} 条日程`);
    await load();
  };

  const importImage = async (file: File) => {
    setImportingImage(true);
    setImportMsg("正在识别课表，大约需要 10–30 秒…");
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api<{ imported: number; skipped: number }>(
        "/api/calendar/import-image",
        { method: "POST", body: form }
      );
      setImportMsg(
        `已识别并导入 ${result.imported} 门课${result.skipped ? `，跳过 ${result.skipped} 条重复` : ""}`
      );
      await load();
    } catch (err: unknown) {
      setImportMsg(err instanceof ApiError ? err.message : "课表识别失败，请换一张图");
    } finally {
      setImportingImage(false);
    }
  };

  const grouped = events.reduce<Record<string, CalendarEvent[]>>((acc, event) => {
    const key = new Date(event.start_at).toLocaleDateString("zh-CN", {
      month: "long",
      day: "numeric",
      weekday: "long"
    });
    (acc[key] ||= []).push(event);
    return acc;
  }, {});

  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <div>
            <h1>日程</h1>
            <p>课表、实验、约会都可以放进来；开始前 30 分钟会尝试推送提醒。</p>
          </div>
          <div className="row" style={{ gap: 8 }}>
            <button
              className="btn primary"
              disabled={importingImage}
              onClick={() => imageRef.current?.click()}
            >
              {importingImage ? <LoaderCircle className="spin" size={14} /> : <Upload size={14} />}
              上传课表图片
            </button>
            <button className="btn ghost" onClick={() => fileRef.current?.click()}>
              <Upload size={14} /> 导入 .ics
            </button>
          </div>
          <input
            ref={imageRef}
            type="file"
            hidden
            accept="image/jpeg,image/png,image/webp"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void importImage(file);
              event.target.value = "";
            }}
          />
          <input
            ref={fileRef}
            type="file"
            hidden
            accept=".ics"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void importIcs(file);
              event.target.value = "";
            }}
          />
        </div>

        {importMsg && (
          <p className="faint" style={{ margin: "-4px 0 14px", fontSize: 12.5 }}>
            {importMsg}
          </p>
        )}

        {conflicts.length > 0 && (
          <div className="conflict-banner">
            <AlertTriangle size={16} />
            <div>
              <strong>有 {conflicts.length} 组日程时间重叠</strong>
              <span>
                {conflicts[0].first.title} 与 {conflicts[0].second.title}
                {conflicts.length > 1 ? " 等" : ""}，建议调整其中一个的时间。
              </span>
            </div>
          </div>
        )}

        <div className="calendar-layout">
          <div className="card">
            <div className="row" style={{ marginBottom: 14 }}>
              <Plus size={16} />
              <strong style={{ fontSize: 14 }}>加一件事</strong>
            </div>
            <div className="form">
              <div className="field">
                <label>标题</label>
                <input
                  className="input"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder="例如：算法实验课"
                />
              </div>
              <div className="field">
                <label>开始时间</label>
                <input
                  className="input"
                  type="datetime-local"
                  value={startAt}
                  onChange={(event) => setStartAt(event.target.value)}
                />
              </div>
              <div className="field">
                <label>地点（可选）</label>
                <input
                  className="input"
                  value={location}
                  onChange={(event) => setLocation(event.target.value)}
                  placeholder="例如：实验楼 302"
                />
              </div>
              <label className="check-row">
                <input type="checkbox" checked={weekly} onChange={(event) => setWeekly(event.target.checked)} />
                每周重复（按这次开始时间的星期）
              </label>
              <button className="btn primary" disabled={!title.trim() || saving} onClick={() => void add()}>
                {saving ? <LoaderCircle className="spin" size={14} /> : <Plus size={14} />}
                加入日程
              </button>
            </div>
          </div>

          <div>
            {loading ? (
              <div className="center" style={{ height: 200 }}>
                <LoaderCircle className="spin" size={18} />
              </div>
            ) : events.length === 0 ? (
              <div className="card empty-card">
                <CalendarDays size={28} />
                <strong>未来 30 天还没有日程</strong>
                <span>手动加一条，或者导入手机日历的 .ics 文件。</span>
              </div>
            ) : (
              <div className="calendar-list">
                {Object.entries(grouped).map(([day, rows]) => (
                  <section key={day} className="calendar-day">
                    <h3>{day}</h3>
                    {rows.map((event) => (
                      <div className="card event-row" key={`${event.id}-${event.start_at}`}>
                        <div className="event-time">
                          <Clock3 size={14} />
                          {new Date(event.start_at).toLocaleTimeString("zh-CN", {
                            hour: "2-digit",
                            minute: "2-digit"
                          })}
                        </div>
                        <div className="event-main">
                          <strong>{event.title}</strong>
                          <span className="faint">
                            {formatWhen(event.start_at)}
                            {event.location ? ` · ${event.location}` : ""}
                            {event.recurrence === "weekly" ? " · 每周" : ""}
                          </span>
                        </div>
                        {event.location && <MapPin size={14} className="faint" />}
                        <button
                          className="icon-btn"
                          title="删除"
                          onClick={async () => {
                            if (!window.confirm(`删除「${event.title}」？`)) return;
                            await api(`/api/calendar/events/${event.id}`, { method: "DELETE" });
                            await load();
                          }}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    ))}
                  </section>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
