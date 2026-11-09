import { useEffect, useState } from "react";
import { Brain, Check, LoaderCircle, RotateCcw, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import type { ReviewItem, ReviewStats } from "../types";

type Filter = "due" | "all" | "mastered";

export function ReviewPage() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [filter, setFilter] = useState<Filter>("due");
  const [loading, setLoading] = useState(true);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [results, setResults] = useState<Record<number, { is_correct: boolean; correct_answer: string; explanation: string }>>({});

  const load = async (next: Filter = filter) => {
    setLoading(true);
    try {
      const query =
        next === "due"
          ? "/api/review/items?due_only=true&limit=100"
          : next === "mastered"
            ? "/api/review/items?status=mastered&limit=100"
            : "/api/review/items?limit=100";
      const [list, summary] = await Promise.all([
        api<ReviewItem[]>(query),
        api<ReviewStats>("/api/review/stats")
      ]);
      setItems(list);
      setStats(summary);
      setResults({});
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(filter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const submit = async (item: ReviewItem) => {
    const answer = answers[item.id];
    if (!answer) return;
    const result = await api<{
      is_correct: boolean;
      correct_answer: string;
      explanation: string;
    }>(`/api/review/items/${item.id}/answer`, {
      method: "POST",
      body: JSON.stringify({ answer })
    });
    setResults((prev) => ({ ...prev, [item.id]: result }));
    window.setTimeout(() => void load(filter), 900);
  };

  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <div>
            <h1>错题本</h1>
            <p>答错的自测题会回到这里，按 3 / 7 / 14 / 30 天的间隔复习。</p>
          </div>
          <span className="badge">{stats ? `${stats.active} 道待掌握` : ""}</span>
        </div>

        {stats && (
          <div className="stat-grid">
            <div className="card stat">
              <span>今天要复习</span>
              <strong>{stats.due}</strong>
            </div>
            <div className="card stat">
              <span>正在复习</span>
              <strong>{stats.active}</strong>
            </div>
            <div className="card stat">
              <span>已掌握</span>
              <strong>{stats.mastered}</strong>
            </div>
            <div className="card stat wide">
              <span>按科目</span>
              <div className="mini-tags">
                {stats.by_course.length === 0 && <em className="faint">还没有错题</em>}
                {stats.by_course.map((row) => (
                  <span className="badge" key={row.course}>
                    {row.course} · {row.count}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}

        <div className="tab-row">
          {(
            [
              ["due", "今天要复习"],
              ["all", "全部"],
              ["mastered", "已掌握"]
            ] as [Filter, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              className={`tab ${filter === key ? "active" : ""}`}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
          <button className="icon-btn" onClick={() => void load(filter)} title="刷新">
            <RotateCcw size={14} />
          </button>
        </div>

        {loading ? (
          <div className="center" style={{ height: 220 }}>
            <LoaderCircle className="spin" size={20} />
          </div>
        ) : items.length === 0 ? (
          <div className="card empty-card">
            <Brain size={28} />
            <strong>这里还没有错题</strong>
            <span>去题库做一套自测，答错的题会自动进来。</span>
          </div>
        ) : (
          <div className="review-list">
            {items.map((item) => {
              const result = results[item.id];
              return (
                <div className="card review-card" key={item.id}>
                  <div className="review-head">
                    <span className="badge">{item.course}</span>
                    {item.chapter && <span className="faint">{item.chapter}</span>}
                    <span className="faint">错 {item.wrong_count} 次 · 复习 {item.review_count} 次</span>
                    {item.status === "mastered" && <span className="badge ok">已掌握</span>}
                    <button
                      className="icon-btn"
                      title="从错题本移除"
                      onClick={async () => {
                        if (!window.confirm("从错题本移除这道题？")) return;
                        await api(`/api/review/items/${item.id}`, { method: "DELETE" });
                        await load(filter);
                      }}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                  <h3>{item.question}</h3>
                  {item.source && <p className="faint review-source">{item.source}</p>}
                  <div className="option-list">
                    {item.options.map((option, index) => {
                      const letter = String.fromCharCode(65 + index);
                      const selected = answers[item.id] === letter;
                      return (
                        <button
                          key={letter}
                          className={`option ${selected ? "selected" : ""}`}
                          onClick={() => setAnswers((prev) => ({ ...prev, [item.id]: letter }))}
                          disabled={Boolean(result)}
                        >
                          <b>{letter}</b>
                          <span>{option}</span>
                        </button>
                      );
                    })}
                  </div>
                  {result && (
                    <div className={`review-result ${result.is_correct ? "ok" : "bad"}`}>
                      <strong>{result.is_correct ? "答对了" : `答错了，正确答案 ${result.correct_answer}`}</strong>
                      {result.explanation && <p>{result.explanation}</p>}
                    </div>
                  )}
                  <div className="review-actions">
                    {!result && (
                      <button
                        className="btn primary"
                        disabled={!answers[item.id]}
                        onClick={() => void submit(item)}
                      >
                        <Check size={14} /> 提交答案
                      </button>
                    )}
                    {result && <span className="faint">已记录，稍后刷新复习计划</span>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
