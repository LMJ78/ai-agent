import { useEffect, useMemo, useState } from "react";
import { Coffee, GraduationCap, Menu } from "lucide-react";
import { Sidebar, type PageKey } from "./components/Sidebar";
import { ChatView } from "./components/ChatView";
import { LoginPage } from "./pages/LoginPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { QuestionBankPage } from "./pages/QuestionBankPage";
import { ApiError, api, clearAuth, getStoredUser, getToken, me } from "./lib/api";
import type {
  AuthResponse,
  ChatSession,
  CourseSummary,
  QuestionItem,
  User
} from "./types";

type Toast = { id: number; text: string; kind: "ok" | "error" };

export default function App() {
  const [user, setUser] = useState<User | null>(() => getStoredUser());
  const [booting, setBooting] = useState(true);
  const [page, setPage] = useState<PageKey>("chat");
  const [mode, setMode] = useState<"study" | "life">("study");
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [activeSession, setActiveSession] = useState<ChatSession | null>(null);
  const [activeCourse, setActiveCourse] = useState("算法设计与分析");
  const [selectedQuestion, setSelectedQuestion] = useState<QuestionItem | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const notify = (text: string, kind: "ok" | "error" = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, text, kind }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((item) => item.id !== id));
    }, 3600);
  };

  const refreshSessions = async (selectId?: number) => {
    try {
      const data = await api<ChatSession[]>("/api/sessions?limit=100");
      setSessions(data);
      if (selectId != null) {
        const found = data.find((item) => item.id === selectId) || null;
        setActiveSession(found);
        if (found?.course) setActiveCourse(found.course);
      }
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) {
        clearAuth();
        setUser(null);
      }
    }
  };

  const refreshCourses = async () => {
    try {
      setCourses(await api<CourseSummary[]>("/api/courses"));
    } catch {
      // 课程列表失败不影响聊天
    }
  };

  const refreshAll = async () => {
    await Promise.all([refreshSessions(), refreshCourses()]);
  };

  useEffect(() => {
    let cancelled = false;
    const boot = async () => {
      if (!getToken()) {
        setBooting(false);
        return;
      }
      try {
        const current = await me();
        if (cancelled) return;
        setUser(current);
        await refreshAll();
      } catch {
        if (!cancelled) {
          clearAuth();
          setUser(null);
        }
      } finally {
        if (!cancelled) setBooting(false);
      }
    };
    void boot();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!user) return;
    void refreshAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  const handleAuthed = (data: AuthResponse) => {
    setUser(data.user);
    setPage("chat");
    setBooting(false);
  };

  const logout = () => {
    clearAuth();
    setUser(null);
    setSessions([]);
    setCourses([]);
    setActiveSession(null);
    setSelectedQuestion(null);
  };

  const changeMode = (next: "study" | "life") => {
    if (next === mode) return;
    setMode(next);
    setSelectedQuestion(null);
    if (activeSession) {
      setActiveSession(null);
      notify(next === "study" ? "已切到学习模式，开一个新对话" : "已切到生活模式，开一个新对话");
    }
  };

  const newChat = () => {
    setPage("chat");
    setActiveSession(null);
    setSelectedQuestion(null);
    setActiveCourse(courses[0]?.name || "算法设计与分析");
  };

  const selectSession = (session: ChatSession) => {
    setPage("chat");
    setActiveSession(session);
    setSelectedQuestion(null);
    setMode(session.mode === "life" ? "life" : "study");
    if (session.course) setActiveCourse(session.course);
  };

  const askQuestion = (question: QuestionItem) => {
    setSelectedQuestion(question);
    setActiveSession(null);
    setMode("study");
    setActiveCourse(question.course || activeCourse);
    setPage("chat");
    notify("题目已放进聊天框，选好节奏后发送");
  };

  const topTitle = useMemo(() => {
    if (page === "knowledge") return "知识库";
    if (page === "questions") return "题库";
    return activeSession?.title || (selectedQuestion ? "讲解这道题" : "新对话");
  }, [page, activeSession, selectedQuestion]);

  if (booting) {
    return <div className="center">正在恢复登录…</div>;
  }

  if (!user) {
    return <LoginPage onAuthed={handleAuthed} />;
  }

  return (
    <div className="app-shell" data-mode={mode}>
      <Sidebar
        user={user}
        sessions={sessions}
        activeSessionId={activeSession?.id ?? null}
        activePage={page}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onSelectSession={selectSession}
        onNewChat={newChat}
        onPage={(next) => {
          setPage(next);
          setSidebarOpen(false);
        }}
        onLogout={logout}
      />

      <main className="main-area">
        <header className="topbar">
          <button className="icon-btn mobile-menu" onClick={() => setSidebarOpen(true)} aria-label="打开菜单">
            <Menu size={18} />
          </button>
          <div className="topbar-title">
            <h1>{topTitle}</h1>
            <p>
              {page === "chat"
                ? `${mode === "study" ? "学习模式" : "生活模式"}${activeCourse ? ` · ${activeCourse}` : ""}`
                : page === "knowledge"
                  ? "你的资料，只给你自己用"
                  : "按科目归档的题目和原图"}
            </p>
          </div>

          {page === "chat" && (
            <div className="mode-switch">
              <button
                className={`mode-btn ${mode === "study" ? "active" : ""}`}
                onClick={() => changeMode("study")}
              >
                <GraduationCap size={13} /> 学习
              </button>
              <button
                className={`mode-btn ${mode === "life" ? "active" : ""}`}
                onClick={() => changeMode("life")}
              >
                <Coffee size={13} /> 生活
              </button>
            </div>
          )}
        </header>

        <div className="content">
          {page === "chat" && (
            <ChatView
              mode={mode}
              courses={courses}
              activeSession={activeSession}
              activeCourse={activeCourse}
              question={selectedQuestion}
              onCourseChange={setActiveCourse}
              onClearQuestion={() => setSelectedQuestion(null)}
              onSessionCreated={(id) => void refreshSessions(id)}
              onSessionsChanged={() => void refreshSessions()}
            />
          )}
          {page === "knowledge" && (
            <KnowledgePage
              courses={courses}
              onChanged={() => void refreshCourses()}
              notify={notify}
            />
          )}
          {page === "questions" && (
            <QuestionBankPage
              courses={courses}
              onAsk={askQuestion}
              notify={notify}
              onChanged={() => void refreshCourses()}
            />
          )}
        </div>
      </main>

      {sidebarOpen && (
        <div
          style={{ position: "fixed", inset: 0, zIndex: 15 }}
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {toasts.map((toast) => (
        <div className={`toast ${toast.kind === "error" ? "error" : ""}`} key={toast.id}>
          {toast.text}
        </div>
      ))}
    </div>
  );
}
