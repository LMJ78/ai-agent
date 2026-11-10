import { useEffect, useState } from "react";
import { BarChart3, Bell, KeyRound, LoaderCircle, Send, Trash2, Wallet } from "lucide-react";
import { ApiError, api } from "../lib/api";
import type { BriefSettings, PushChannelState, UsageSummary } from "../types";

type Props = {
  notify: (message: string, kind?: "ok" | "error") => void;
};

export function SettingsPage({ notify }: Props) {
  const [cfg, setCfg] = useState<BriefSettings | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [push, setPush] = useState<PushChannelState | null>(null);
  const [pushToken, setPushToken] = useState("");
  const [saving, setSaving] = useState(false);
  const [savingPush, setSavingPush] = useState(false);
  const [testingPush, setTestingPush] = useState(false);
  const [testing, setTesting] = useState<"morning" | "evening" | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [settings, summary, channel] = await Promise.all([
        api<BriefSettings>("/api/settings"),
        api<UsageSummary>("/api/usage/summary?days=30"),
        api<PushChannelState>("/api/push/channel")
      ]);
      setCfg(settings);
      setUsage(summary);
      setPush(channel);
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

  const savePush = async () => {
    const token = pushToken.trim();
    if (!token) {
      notify("先把 PushPlus token 粘贴进来", "error");
      return;
    }
    setSavingPush(true);
    try {
      const channel = await api<PushChannelState>("/api/push/channel", {
        method: "PUT",
        body: JSON.stringify({ token, enabled: true })
      });
      setPush(channel);
      setPushToken("");
      notify("PushPlus 通道已保存");
    } catch (err: unknown) {
      notify(err instanceof ApiError ? err.message : "保存失败", "error");
    } finally {
      setSavingPush(false);
    }
  };

  const testPush = async () => {
    setTestingPush(true);
    try {
      await api<{ ok: boolean }>("/api/push/test", { method: "POST" });
      notify("测试消息已发送，请检查微信");
    } catch (err: unknown) {
      notify(err instanceof ApiError ? err.message : "发送失败，请检查 token", "error");
    } finally {
      setTestingPush(false);
    }
  };

  const removePush = async () => {
    if (!window.confirm("删除 PushPlus 通道？删除后待办和简报不会再推送。")) return;
    try {
      await api("/api/push/channel", { method: "DELETE" });
      setPush({
        provider: "pushplus",
        configured: false,
        enabled: false,
        token_masked: ""
      });
      notify("PushPlus 通道已删除");
    } catch (err: unknown) {
      notify(err instanceof ApiError ? err.message : "删除失败", "error");
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

        <div className="card" style={{ marginTop: 16 }}>
          <div className="row" style={{ marginBottom: 8 }}>
            <KeyRound size={17} />
            <strong>PushPlus 推送</strong>
            <span className={`push-badge ${push?.configured ? "on" : ""}`}>
              {push?.configured ? `已配置 ${push.token_masked}` : "未配置"}
            </span>
          </div>
          <p className="faint" style={{ margin: "0 0 12px" }}>
            待办到点、日程开始前 30 分钟、早晚简报都走这里。去 pushplus.plus
            微信扫码登录，复制 token 粘贴到下面；只需配置一次。
          </p>
          <div className="push-form">
            <input
              className="input"
              type="password"
              value={pushToken}
              onChange={(event) => setPushToken(event.target.value)}
              placeholder={push?.configured ? "粘贴新 token 可替换当前通道" : "粘贴 PushPlus token"}
              autoComplete="off"
            />
            <button className="btn primary" disabled={savingPush} onClick={() => void savePush()}>
              {savingPush ? <LoaderCircle className="spin" size={14} /> : null}
              保存通道
            </button>
            <button
              className="btn ghost"
              disabled={!push?.configured || testingPush}
              onClick={() => void testPush()}
            >
              {testingPush ? <LoaderCircle className="spin" size={13} /> : <Send size={13} />}
              发送测试
            </button>
            {push?.configured && (
              <button className="btn ghost" onClick={() => void removePush()}>
                <Trash2 size={13} /> 删除
              </button>
            )}
          </div>
          <p className="faint" style={{ margin: "10px 0 0", fontSize: 12 }}>
            没配通道时，简报和提醒只会生成内容，不会发送；微信里没收到测试消息，先检查
            token 是否复制完整。
          </p>
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
