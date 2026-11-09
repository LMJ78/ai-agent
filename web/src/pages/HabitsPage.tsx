import { useEffect, useState } from "react";
import { Check, Flame, LoaderCircle, Plus, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import type { Habit } from "../types";

const ICONS = ["✅", "💧", "🏃", "📚", "🧘", "🌙", "🥗", "✍️"];

export function HabitsPage() {
  const [habits, setHabits] = useState<Habit[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [icon, setIcon] = useState("✅");

  const load = async () => {
    setLoading(true);
    try {
      setHabits(await api<Habit[]>("/api/habits"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const add = async () => {
    if (!name.trim()) return;
    await api<Habit>("/api/habits", {
      method: "POST",
      body: JSON.stringify({ name: name.trim(), icon })
    });
    setName("");
    await load();
  };

  const toggle = async (habit: Habit) => {
    const updated = await api<Habit>(`/api/habits/${habit.id}/toggle`, { method: "POST" });
    setHabits((prev) =>
      prev.map((item) =>
        item.id === habit.id
          ? { ...item, done_today: updated.done_today, streak: updated.streak }
          : item
      )
    );
  };

  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <div>
            <h1>习惯</h1>
            <p>每天点一下，连续天数会自己累计。别贪多，先养一个。</p>
          </div>
          <span className="badge">今天 {habits.filter((item) => item.done_today).length} / {habits.length}</span>
        </div>

        <div className="card habit-add">
          <div className="habit-icon-picker">
            {ICONS.map((emoji) => (
              <button
                key={emoji}
                className={`habit-emoji ${icon === emoji ? "active" : ""}`}
                onClick={() => setIcon(emoji)}
              >
                {emoji}
              </button>
            ))}
          </div>
          <div className="row" style={{ gap: 8 }}>
            <input
              className="input"
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void add();
              }}
              placeholder="新习惯，例如：每天背 30 个单词"
            />
            <button className="btn primary" disabled={!name.trim()} onClick={() => void add()}>
              <Plus size={14} /> 加入
            </button>
          </div>
        </div>

        {loading ? (
          <div className="center" style={{ height: 200 }}>
            <LoaderCircle className="spin" size={18} />
          </div>
        ) : habits.length === 0 ? (
          <div className="card empty-card">
            <Flame size={28} />
            <strong>还没有习惯</strong>
            <span>先加一个最容易坚持的，比如喝水或早睡。</span>
          </div>
        ) : (
          <div className="habit-grid">
            {habits.map((habit) => (
              <div className={`card habit-card ${habit.done_today ? "done" : ""}`} key={habit.id}>
                <div className="habit-emoji big">{habit.icon}</div>
                <div className="habit-main">
                  <strong>{habit.name}</strong>
                  <span className="faint">
                    连续 {habit.streak} 天 · 本周 {habit.week_done} 次
                  </span>
                </div>
                <button
                  className={`habit-check ${habit.done_today ? "checked" : ""}`}
                  onClick={() => void toggle(habit)}
                  aria-label={habit.done_today ? "取消打卡" : "打卡"}
                >
                  {habit.done_today ? <Check size={18} /> : <span />}
                </button>
                <button
                  className="icon-btn"
                  title="删除习惯"
                  onClick={async () => {
                    if (!window.confirm(`删除「${habit.name}」？打卡记录也会一起删掉。`)) return;
                    await api(`/api/habits/${habit.id}`, { method: "DELETE" });
                    await load();
                  }}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
