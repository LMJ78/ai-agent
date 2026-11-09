import { useEffect, useState } from "react";
import { BarChart3, Bell, LoaderCircle, Send, Wallet } from "lucide-react";
import { ApiError, api } from "../lib/api";
import type { BriefSettings, UsageSummary } from "../types";

type Props = {
  notify: (message: string, kind?: "ok" | "error") => void;
};

export function SettingsPage({ notify }: Props) {
  const [cfg, setCfg] = useState<BriefSettings | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<"morning" | "evening" | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [settings, summary] = await Promise.all([
        api<BriefSettings>("/api/settings"),
        api<UsageSummary>("/api/usage/summary?days=30")
      ]);
      setCfg(settings);
      setUsage(summary);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const save = async () => {
    if (!cfg) return;
    setSaving(true);
    try {
      setCfg(
        await api<BriefSettings>("/api/settings", {
          method: "PUT",
          body: JSON.stringify(cfg)
        })
      );
      notify("设置已保存");
    } catch (err: unknown) {
      notify(err instanceof ApiError ? err.message : "保存失败", "error");
    } finally {
      setSaving(false);
    }
  };

  const test = async (kind: "morning" | "evening") => {
    setTesting(kind);
    try {
      const result = await api<{ preview: string }>(`/api/settings/brief/test?kind=${kind}`, {
        method: "POST"
      });
      notify(`测试消息已发到 PushPlus：${result.preview.slice(0, 60)}…`);
    } catch (err: unknown) {
      notify(err instanceof ApiError ? err.message : "发送失败", "error");
    } finally {
      setTesting(null);
    }
  };

  if (loading || !cfg) {
    return (
      <div className="center" style={{ height: "60vh" }}>
        <LoaderCircle className="spin" size={20} />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <div>
            <h1>设置与用量</h1>
            <p>早晚简报通过 PushPlus 推送；用量按 DeepSeek 实际返回的 token 估算费用。</p>
          </div>
        </div>

        <div className="settings-grid">
          <div className="card">
            <div className="row" style={{ marginBottom: 16 }}>
              <Bell size={17} />
              <strong>每日简报 / 晚间复盘</strong>
            </div>
            <div className="form">
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={cfg.morning_enabled}
                  onChange={(event) => setCfg({ ...cfg, morning_enabled: event.target.checked })}
                />
                每天推送早间简报
              </label>
              <div className="field inline">
                <label>时间</label>
                <input
                  className="input"
                  type="time"
                  value={cfg.morning_time}
                  onChange={(event) => setCfg({ ...cfg, morning_time: event.target.value })}
                />
                <button
                  className="btn ghost"
                  disabled={testing !== null}
                  onClick={() => void test("morning")}
                >
                  {testing === "morning" ? <LoaderCircle className="spin" size={13} /> : <Send size={13} />}
                  测试
                </button>
              </div>

              <label className="check-row" style={{ marginTop: 12 }}>
                <input
                  type="checkbox"
                  checked={cfg.evening_enabled}
                  onChange={(event) => setCfg({ ...cfg, evening_enabled: event.target.checked })}
                />
                每天推送晚间复盘
              </label>
              <div className="field inline">
                <label>时间</label>
                <input
                  className="input"
                  type="time"
                  value={cfg.evening_time}
                  onChange={(event) => setCfg({ ...cfg, evening_time: event.target.value })}
                />
                <button
                  className="btn ghost"
                  disabled={testing !== null}
                  onClick={() => void test("evening")}
                >
                  {testing === "evening" ? <LoaderCircle className="spin" size={13} /> : <Send size={13} />}
                  测试
                </button>
              </div>

              <div className="field">
                <label>新闻主题（可选）</label>
                <input
                  className="input"
                  value={cfg.news_topics}
                  onChange={(event) => setCfg({ ...cfg, news_topics: event.target.value })}
                  placeholder="例如：AI、算法竞赛、科技"
                />
              </div>
              <button className="btn primary" disabled={saving} onClick={() => void save()}>
                {saving ? <LoaderCircle className="spin" size={14} /> : null}
                保存设置
              </button>
            </div>
          </div>

          <div className="card">
            <div className="row" style={{ marginBottom: 16 }}>
              <Wallet size={17} />
              <strong>近 30 天用量</strong>
            </div>
            {usage ? (
              <>
                <div className="usage-stats">
                  <div>
                    <span>轮次</span>
                    <strong>{usage.total_turns}</strong>
                  </div>
                  <div>
                    <span>输入 tokens</span>
                    <strong>{usage.total_input_tokens.toLocaleString()}</strong>
                  </div>
                  <div>
                    <span>输出 tokens</span>
                    <strong>{usage.total_output_tokens.toLocaleString()}</strong>
                  </div>
                  <div>
                    <span>估算费用</span>
                    <strong>¥{usage.total_cost_yuan.toFixed(2)}</strong>
                  </div>
                </div>
                <div className="usage-table">
                  {usage.series
                    .filter((row) => row.turns > 0)
                    .slice(-10)
                    .reverse()
                    .map((row) => (
                      <div className="usage-row" key={row.date}>
                        <span>{row.date.slice(5)}</span>
                        <span>{row.turns} 轮</span>
                        <span>{(row.input_tokens + row.output_tokens).toLocaleString()} tok</span>
                        <span>¥{row.cost_yuan.toFixed(3)}</span>
                      </div>
                    ))}
                  {usage.series.every((row) => row.turns === 0) && (
                    <p className="faint" style={{ margin: 0 }}>
                      还没有用量记录，聊几轮再来看。
                    </p>
                  )}
                </div>
              </>
            ) : (
              <div className="center" style={{ height: 120 }}>
                <LoaderCircle className="spin" size={16} />
              </div>
            )}
          </div>
        </div>

        <div className="card usage-note">
          <BarChart3 size={16} />
          <p>
            费用按输入 ¥2 / 百万 token、输出 ¥8 / 百万 token 估算，只统计聊天回复的
            token；实际账单以 DeepSeek 控制台为准。
          </p>
        </div>
      </div>
    </div>
  );
}
