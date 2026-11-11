import { useEffect, useState } from "react";
import { Brain, Check, LoaderCircle, RotateCcw, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import type { ReviewItem, ReviewMastery, ReviewPlan, ReviewStats } from "../types";

type Filter = "due" | "all" | "mastered";

export function ReviewPage() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [mastery, setMastery] = useState<ReviewMastery[]>([]);
  const [examDate, setExamDate] = useState("");
  const [plan, setPlan] = useState<ReviewPlan | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [filter, setFilter] = useState<Filter>("due");
  const [loading, setLoading] = useState(true);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [revealed, setRevealed] = useState<Record<number, boolean>>({});
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
      const [list, summary, masteryRows] = await Promise.all([
        api<ReviewItem[]>(query),
        api<ReviewStats>("/api/review/stats"),
        api<ReviewMastery[]>("/api/review/mastery")
      ]);
      setItems(list);
      setStats(summary);
      setMastery(masteryRows);
      setResults({});
      setRevealed({});
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
    // 保留当前卡片和结果，避免刚显示“答对了”就被刷新掉；
    // 只更新统计，用户切换筛选或点刷新时再重新拉列表。
    void api<ReviewStats>("/api/review/stats").then(setStats).catch(() => undefined);
  };

  const selfCheck = async (item: ReviewItem, result: "correct" | "wrong") => {
    const data = await api<{
      is_correct: boolean;
      correct_answer: string;
      explanation: string;
    }>(`/api/review/items/${item.id}/self-check`, {
      method: "POST",
      body: JSON.stringify({ result })
    });
    setResults((prev) => ({ ...prev, [item.id]: data }));
    void api<ReviewStats>("/api/review/stats").then(setStats).catch(() => undefined);
  };

  const makePlan = async () => {
    if (!examDate) return;
    setPlanLoading(true);
    try {
      const data = await api<ReviewPlan>(
        `/api/review/plan?exam_date=${encodeURIComponent(examDate)}`
      );
      setPlan(data);
    } finally {
      setPlanLoading(false);
    }
  };

  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <div>
            <h1>错题本</h1>
            <p>自测答错会自动收录；聊天讲解完也可以手动加入。按 3 / 7 / 14 / 30 天复习。</p>
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

        <div className="study-loop-grid">
          <div className="card study-loop-card">
            <div className="card-head">
              <div>
                <strong>章节掌握度</strong>
                <p>答对越多，进度条越满；先补最短的那块。</p>
              </div>
            </div>
            {mastery.length === 0 ? (
              <p className="faint">还没有数据，先做一套自测或从聊天加入错题。</p>
            ) : (
              <div className="mastery-list">
                {mastery.slice(0, 8).map((row) => (
                  <div className="mastery-row" key={`${row.course}-${row.chapter}`}>
                    <div className="mastery-label">
                      <span>{row.chapter}</span>
                      <span className="faint">
                        {row.mastered}/{row.total}
                      </span>
                    </div>
                    <div className="mastery-bar">
                      <i style={{ width: `${row.mastery}%` }} />
                    </div>
                    {row.due > 0 && <span className="badge warn">到期 {row.due}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card study-loop-card">
            <div className="card-head">
              <div>
                <strong>考前冲刺</strong>
                <p>填考试日期，按剩余天数排每天复习量。</p>
              </div>
            </div>
            <div className="plan-form">
              <input
                type="date"
                className="field-input"
                value={examDate}
                onChange={(event) => setExamDate(event.target.value)}
              />
              <button className="btn primary" disabled={!examDate || planLoading} onClick={() => void makePlan()}>
                {planLoading ? "计算中…" : "生成计划"}
              </button>
            </div>
            {plan && (
              <div className="plan-result">
                <strong>{plan.message}</strong>
                <div className="mini-tags">
                  <span className="badge">剩 {plan.days} 天</span>
                  <span className="badge">待复习 {plan.active}</span>
                  <span className="badge">今天到期 {plan.due}</span>
                  <span className="badge ok">每天 {plan.daily_target} 道</span>
                </div>
                {plan.weak_chapters.length > 0 && (
                  <p className="faint">
                    优先章节：
                    {plan.weak_chapters.map((row) => `${row.chapter}（${row.mastery}%）`).join("、")}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>

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
            <span>去题库做自测，答错会自动进来；聊天回答下方也能点「加入错题本」。</span>
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
                  {item.options.length > 0 ? (
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
                  ) : (
                    <div className="recall-box">
                      {!revealed[item.id] && !result ? (
                        <p className="faint">先自己在心里过一遍，再点开参考答案。</p>
                      ) : (
                        <div className="recall-answer">
                          <span className="faint">参考答案</span>
                          <p>{item.answer || "这道题没有填写参考答案，按你的理解自评即可。"}</p>
                        </div>
                      )}
                    </div>
                  )}
                  {result && (
                    <div className={`review-result ${result.is_correct ? "ok" : "bad"}`}>
                      <strong>
                        {item.options.length > 0
                          ? result.is_correct
                            ? "答对了"
                            : `答错了，正确答案 ${result.correct_answer}`
                          : result.is_correct
                            ? "记住了，间隔会拉长"
                            : "这次没记住，明天再来一次"}
                      </strong>
                      {result.explanation && <p>{result.explanation}</p>}
                    </div>
                  )}
                  <div className="review-actions">
                    {!result && item.options.length > 0 && (
                      <button
                        className="btn primary"
                        disabled={!answers[item.id]}
                        onClick={() => void submit(item)}
                      >
                        <Check size={14} /> 提交答案
                      </button>
                    )}
                    {!result && item.options.length === 0 && !revealed[item.id] && (
                      <button
                        className="btn ghost"
                        onClick={() => setRevealed((prev) => ({ ...prev, [item.id]: true }))}
                      >
                        显示参考答案
                      </button>
                    )}
                    {!result && item.options.length === 0 && revealed[item.id] && (
                      <>
                        <button className="btn primary" onClick={() => void selfCheck(item, "correct")}>
                          <Check size={14} /> 我记住了
                        </button>
                        <button className="btn ghost" onClick={() => void selfCheck(item, "wrong")}>
                          没记住
                        </button>
                      </>
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
