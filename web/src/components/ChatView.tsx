import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  BookOpen,
  Coffee,
  Copy,
  GraduationCap,
  Square,
  Sparkles,
  X
} from "lucide-react";
import { ApiError, api, streamChat } from "../lib/api";
import type { ChatMessage, ChatSession, CourseSummary, QuestionItem, ToolTrace } from "../types";
import { Markdown } from "./Markdown";

type UiMessage = ChatMessage & { key: string };
type Stage = "auto" | "hint" | "step" | "answer";

type Props = {
  mode: "study" | "life";
  courses: CourseSummary[];
  activeSession: ChatSession | null;
  activeCourse: string;
  question: QuestionItem | null;
  onCourseChange: (course: string) => void;
  onClearQuestion: () => void;
  onSessionCreated: (id: number) => void;
  onSessionsChanged: () => void;
};

const SUGGESTIONS = {
  study: [
    "0-1 背包的状态转移方程怎么推？",
    "用课件里的例子讲讲动态规划",
    "帮我看看这道题从哪一步开始想",
    "快速排序的平均复杂度为什么是 O(n log n)？"
  ],
  life: [
    "今天有点累，陪我聊两句",
    "我最近总是拖延，怎么办？",
    "帮我安排一下明天的时间",
    "记住我周四下午有实验课"
  ]
};

const STAGES: { key: Stage; label: string }[] = [
  { key: "auto", label: "自动" },
  { key: "hint", label: "先提示" },
  { key: "step", label: "下一步" },
  { key: "answer", label: "看答案" }
];

function newKey(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function ChatView({
  mode,
  courses,
  activeSession,
  activeCourse,
  question,
  onCourseChange,
  onClearQuestion,
  onSessionCreated,
  onSessionsChanged
}: Props) {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [stage, setStage] = useState<Stage>("auto");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [sessionId, setSessionId] = useState<number | null>(activeSession?.id ?? null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const skipLoadRef = useRef<number | null>(null);

  useEffect(() => {
    setSessionId(activeSession?.id ?? null);
    setError("");
  }, [activeSession?.id]);

  useEffect(() => {
    // 新会话刚由 SSE 创建时，App 会刷新列表并选中它。这里必须先跳过，
    // 否则会中止正在进行的流式请求，assistant 气泡永远为空。
    if (activeSession && skipLoadRef.current === activeSession.id) {
      skipLoadRef.current = null;
      return;
    }

    let cancelled = false;
    setLoading(false);
    abortRef.current?.abort();
    if (!activeSession) {
      setMessages([]);
      return;
    }
    api<{ messages: ChatMessage[] }>(`/api/sessions/${activeSession.id}/messages`)
      .then((data) => {
        if (cancelled) return;
        setMessages(
          data.messages
            .filter((item) => item.role === "user" || item.role === "assistant")
            .map((item) => ({ ...item, key: `db-${item.id ?? newKey()}` }))
        );
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载对话失败");
      });
    return () => {
      cancelled = true;
    };
  }, [activeSession?.id]);

  useEffect(() => {
    // 空状态不滚动，否则欢迎语会被顶出屏幕；有消息时才跟到底部。
    if (messages.length === 0) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, loading]);

  const currentCourse = question?.course || activeCourse || courses[0]?.name || "算法设计与分析";
  const canSend = !loading && (input.trim().length > 0 || Boolean(question));

  const updateAssistant = (key: string, updater: (message: UiMessage) => UiMessage) => {
    setMessages((prev) => prev.map((item) => (item.key === key ? updater(item) : item)));
  };

  const send = async () => {
    if (!canSend) return;
    const text = input.trim();
    const activeQuestion = question;
    const userKey = newKey();
    const assistantKey = newKey();
    const userMessage: UiMessage = {
      key: userKey,
      role: "user",
      content: text || `（讲解这道题：${activeQuestion?.parsed_text.slice(0, 40) || ""}…）`,
      created_at: new Date().toISOString()
    };
    const assistantMessage: UiMessage = {
      key: assistantKey,
      role: "assistant",
      content: "",
      trace: [],
      pending: true,
      created_at: new Date().toISOString()
    };
    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setInput("");
    setError("");
    setLoading(true);
    onClearQuestion();

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamChat(
        {
          message: text || "请讲解这道题。",
          session_id: sessionId,
          mode,
          course: mode === "study" ? currentCourse : undefined,
          question_id: activeQuestion?.id,
          teaching_stage: stage === "auto" ? undefined : stage
        },
        {
          onSession: (id) => {
            setSessionId(id);
            skipLoadRef.current = id;
            onSessionCreated(id);
          },
          onDelta: (delta) => {
            updateAssistant(assistantKey, (item) => ({ ...item, content: item.content + delta }));
          },
          onTool: (event) => {
            updateAssistant(assistantKey, (item) => {
              const trace: ToolTrace = {
                type: event.type,
                name: event.name,
                arguments: event.arguments,
                content: event.content
              };
              return { ...item, trace: [...(item.trace || []), trace] };
            });
          },
          onError: (message) => setError(message)
        },
        controller.signal
      );
    } catch (err: unknown) {
      if ((err as Error)?.name !== "AbortError") {
        const message =
          err instanceof ApiError ? err.message : err instanceof Error ? err.message : "请求失败";
        setError(message);
        updateAssistant(assistantKey, (item) => ({
          ...item,
          content: item.content || `这次没有成功：${message}`
        }));
      }
    } finally {
      setLoading(false);
      abortRef.current = null;
      updateAssistant(assistantKey, (item) => ({ ...item, pending: false }));
      onSessionsChanged();
    }
  };

  const stop = () => {
    abortRef.current?.abort();
    setLoading(false);
  };

  const copy = async (content: string) => {
    try {
      await navigator.clipboard.writeText(content);
    } catch {
      // 浏览器不允许时静默失败，不打断对话
    }
  };

  const showEmpty = messages.length === 0 && !loading;

  const courseOptions = useMemo(() => {
    const names = new Set(courses.map((item) => item.name));
    if (currentCourse) names.add(currentCourse);
    return Array.from(names).filter(Boolean);
  }, [courses, currentCourse]);

  return (
    <div className="chat-page">
      <div className="chat-scroll" ref={scrollRef}>
        <div className="chat-inner">
          {showEmpty ? (
            <div className="empty-state">
              <div className="empty-mark">
                {mode === "study" ? <GraduationCap size={27} /> : <Coffee size={27} />}
              </div>
              <h2>{mode === "study" ? "今天想学点什么？" : "今天过得怎么样？"}</h2>
              <p>
                {mode === "study"
                  ? "可以追问课件概念、让我一步一步讲题，或者直接来一套考前自测。"
                  : "不用急着解决问题。先说说今天发生了什么，我会记住你在意的事。"}
              </p>

              {mode === "study" && (
                <div className="course-picker">
                  {courseOptions.map((course) => (
                    <button
                      key={course}
                      className={`course-pill ${course === currentCourse ? "active" : ""}`}
                      onClick={() => onCourseChange(course)}
                    >
                      {course}
                    </button>
                  ))}
                </div>
              )}

              <div className="suggestions">
                {SUGGESTIONS[mode].map((text) => (
                  <button
                    className="suggestion"
                    key={text}
                    onClick={() => {
                      setInput(text);
                      textareaRef.current?.focus();
                    }}
                  >
                    <Sparkles size={13} style={{ marginBottom: -2, marginRight: 6 }} />
                    {text}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="messages">
              {messages.map((message) => (
                <div className={`message ${message.role}`} key={message.key}>
                  <div className="message-avatar">
                    {message.role === "assistant" ? "伴" : "我"}
                  </div>
                  <div className="message-body">
                    {message.trace && message.trace.length > 0 && (
                      <div className="tool-trace">
                        {message.trace.map((trace, index) => (
                          <span className="tool-chip" key={`${message.key}-tool-${index}`}>
                            {trace.type === "tool_call"
                              ? `调用 ${trace.name || "工具"}`
                              : `${trace.name || "工具"} 已返回`}
                          </span>
                        ))}
                      </div>
                    )}
                    {message.role === "assistant" ? (
                      <div className="bubble">
                        {message.content ? (
                          <Markdown>{message.content}</Markdown>
                        ) : (
                          <span className="typing">
                            <i />
                            <i />
                            <i />
                          </span>
                        )}
                      </div>
                    ) : (
                      <div className="bubble">{message.content}</div>
                    )}
                    {message.role === "assistant" && message.content && !message.pending && (
                      <div className="message-actions">
                        <button onClick={() => copy(message.content)}>
                          <Copy size={11} style={{ marginRight: 4 }} />
                          复制
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="composer">
        <div className="composer-inner">
          {error && <div className="error-banner">{error}</div>}
          {question && (
            <div className="selected-question">
              <BookOpen size={13} />
              <span>
                正在讲：{question.course} · {question.parsed_text.slice(0, 70)}
              </span>
              <button className="icon-btn" onClick={onClearQuestion} aria-label="取消选题">
                <X size={13} />
              </button>
            </div>
          )}
          {mode === "study" && (
            <div className="stage-row">
              <span className="faint" style={{ fontSize: 10.5 }}>
                讲题节奏
              </span>
              {STAGES.map((item) => (
                <button
                  key={item.key}
                  className={`stage-chip ${stage === item.key ? "active" : ""}`}
                  onClick={() => setStage(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          )}
          <div className="composer-box">
            <textarea
              ref={textareaRef}
              value={input}
              rows={1}
              placeholder={
                question
                  ? "可以直接发送，让老师按这道题讲；也可以补充你的卡点"
                  : mode === "study"
                    ? "问课件、问题目，或者让我一步一步讲…"
                    : "说说今天的事，或者让我记住一件重要的事…"
              }
              onChange={(event) => {
                setInput(event.target.value);
                const el = event.currentTarget;
                el.style.height = "auto";
                el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
              }}
            />
            {loading ? (
              <button className="send-btn" onClick={stop} title="停止生成">
                <Square size={13} fill="currentColor" />
              </button>
            ) : (
              <button className="send-btn" onClick={() => void send()} disabled={!canSend} title="发送">
                <ArrowUp size={17} />
              </button>
            )}
          </div>
          <div className="composer-hint">Enter 发送 · Shift + Enter 换行 · 回答中的 [L] 来自课件</div>
        </div>
      </div>
    </div>
  );
}
