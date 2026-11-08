import { FormEvent, useState } from "react";
import { ArrowRight, GraduationCap, LoaderCircle } from "lucide-react";
import { ApiError, login, register, saveAuth } from "../lib/api";
import type { AuthResponse } from "../types";

type Props = {
  onAuthed: (data: AuthResponse) => void;
};

export function LoginPage({ onAuthed }: Props) {
  const [tab, setTab] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (loading) return;
    setError("");
    setLoading(true);
    try {
      const data =
        tab === "login"
          ? await login(username.trim(), password)
          : await register({
              username: username.trim(),
              password,
              display_name: displayName.trim() || username.trim(),
              invite_code: inviteCode.trim()
            });
      saveAuth(data);
      onAuthed(data);
    } catch (err: unknown) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "登录失败，请稍后再试"
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <div className="brand-mark">
            <GraduationCap size={19} />
          </div>
          <div>
            <h1>伴学</h1>
            <p>把课件、题目和生活里的事，放在一个地方</p>
          </div>
        </div>

        <div className="login-tabs">
          <button className={tab === "login" ? "active" : ""} onClick={() => setTab("login")}>
            登录
          </button>
          <button
            className={tab === "register" ? "active" : ""}
            onClick={() => setTab("register")}
          >
            注册
          </button>
        </div>

        <form className="form" onSubmit={(event) => void submit(event)}>
          <div className="field">
            <label>用户名</label>
            <input
              className="input"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              placeholder="3–32 位字母、数字或下划线"
              required
            />
          </div>

          {tab === "register" && (
            <div className="field">
              <label>怎么称呼你</label>
              <input
                className="input"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="例如：小明"
                maxLength={32}
              />
            </div>
          )}

          <div className="field">
            <label>密码</label>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={tab === "login" ? "current-password" : "new-password"}
              placeholder={tab === "register" ? "至少 8 位" : "输入密码"}
              required
            />
          </div>

          {tab === "register" && (
            <div className="field">
              <label>邀请码</label>
              <input
                className="input"
                value={inviteCode}
                onChange={(event) => setInviteCode(event.target.value)}
                placeholder="AI-XXXXXXXX"
                required
              />
            </div>
          )}

          {error && <div className="error-banner" style={{ margin: 0 }}>{error}</div>}

          <button className="btn primary" type="submit" disabled={loading} style={{ justifyContent: "center", padding: "11px" }}>
            {loading ? <LoaderCircle className="spin" size={15} /> : <ArrowRight size={15} />}
            {tab === "login" ? "进入伴学" : "用邀请码注册"}
          </button>
        </form>

        <div className="login-note">
          第一次用？找管理员要一个邀请码。
          <br />
          这是一个小范围试用的学习助手，不是公开产品。
        </div>
      </div>
    </div>
  );
}
