import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  BookmarkPlus,
  BookOpen,
  Coffee,
  Copy,
  ExternalLink,
  FileText,
  GraduationCap,
  Square,
  Sparkles,
  X
} from "lucide-react";
import { ApiError, api, getToken, streamChat } from "../lib/api";
import type {
  ChatMessage,
  ChatSession,
  Citation,
  CourseSummary,
  QuestionItem,
  ToolTrace
} from "../types";
import { Markdown } from "./Markdown";

type UiMessage = ChatMessage & { key: string; questionText?: string };
type Stage = "auto" | "hint" | "step" | "answer";
type ReviewDraft = {
  kind: "recall" | "choice";
  question: string;
  answer: string;
  explanation: string;
  course: string;
  chapter: string;
  source: string;
  options: string[];
  correctAnswer: string;
};

const LETTERS = ["A", "B", "C", "D"];

// 错题本用纯文本展示，保存前去掉常见的 Markdown 标记，避免题干里出现 ** 或 #。
function stripMarkdown(value: string): string {
  return value
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/^\s*[-*]\s+/gm, "")
    .trim();
}

function parseChoiceDraft(text: string): Pick<ReviewDraft, "question" | "options" | "correctAnswer"> | null {
  const lines = text.split(/\r?\n/);
  const found: { letter: string; text: string; index: number }[] = [];
  lines.forEach((line, index) => {
    const match = line.match(/^\s*(?:[-*]\s*)?\**([A-D])[.、．]\s*(.+?)\s*$/);
    if (match && !found.some((item) => item.letter === match[1])) {
      found.push({ letter: match[1], text: match[2].replace(/\**$/, "").trim(), index });
    }
  });
  if (found.length < 4) return null;
  const answerMatch = text.match(/(?:正确答案|答案)\s*[：:]\s*\**([A-D])\b/);
  if (!answerMatch) return null;

  const firstOption = found.sort((a, b) => a.index - b.index)[0];
  const before = lines.slice(0, firstOption.index).join("\n");
  const questionMatch = before.match(/(?:题目(?:（[^）]*）)?\s*\**\s*:?\s*\n+)([\s\S]+)$/);
  const question = (questionMatch?.[1] || before).replace(/^\s*[-*]\s*/gm, "").trim();

  return {
    question: stripMarkdown(question).slice(0, 4000),
    options: LETTERS.map((letter) => stripMarkdown(found.find((item) => item.letter === letter)?.text || "")),
    correctAnswer: answerMatch[1]
  };
}


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
  const [feynman, setFeynman] = useState(false);
  const [preview, setPreview] = useState<Citation | null>(null);
  const [reviewDraft, setReviewDraft] = useState<ReviewDraft | null>(null);
  const [reviewTargetKey, setReviewTargetKey] = useState<string | null>(null);
  const [reviewSaved, setReviewSaved] = useState<Record<string, boolean>>({});
  const [reviewSaving, setReviewSaving] = useState(false);
  const [reviewError, setReviewError] = useState("");
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

  const openCitation = async (citation: Citation) => {
    if (citation.type === "web" && citation.url) {
      window.open(citation.url, "_blank", "noopener,noreferrer");
      return;
    }
    setPreview(citation);
  };

  const openNoteFile = async (citation: Citation) => {
    if (!citation.document_id) return;
    try {
      const res = await fetch(`/api/documents/${citation.document_id}/file`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      if (!res.ok) throw new Error("原文件打不开");
      const url = URL.createObjectURL(await res.blob());
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "原文件打不开");
    }
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
      questionText: activeQuestion?.parsed_text || text || undefined,
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
          teaching_stage: stage === "auto" ? undefined : stage,
          feynman
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
          onCitations: (citations) => {
            updateAssistant(assistantKey, (item) => ({ ...item, citations }));
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

  const openReviewDraft = (message: UiMessage) => {
    const index = messages.findIndex((item) => item.key === message.key);
    const previousUser = [...messages.slice(0, index)]
      .reverse()
      .find((item) => item.role === "user");
    const parsed = parseChoiceDraft(message.content);
    const fallbackQuestion = message.questionText || previousUser?.content || "";
    setReviewDraft({
      kind: parsed ? "choice" : "recall",
      question: parsed?.question || fallbackQuestion,
      answer: parsed ? "" : message.content,
      explanation: parsed ? message.content : "",
      course: currentCourse,
      chapter: "",
      source: "聊天 · 手动加入",
      options: parsed?.options || ["", "", "", ""],
      correctAnswer: parsed?.correctAnswer || ""
    });
    setReviewTargetKey(message.key);
    setReviewError("");
  };

  const saveReview = async () => {
    if (!reviewDraft) return;
    if (!reviewDraft.question.trim()) {
      setReviewError("题目不能为空，补一句题干再保存。");
      return;
    }
    const isChoice = reviewDraft.kind === "choice";
    if (isChoice) {
      if (reviewDraft.options.some((option) => !option.trim())) {
        setReviewError("选择题要把 A–D 四个选项都填上。");
        return;
      }
      if (!reviewDraft.correctAnswer) {
        setReviewError("请选择正确答案。");
        return;
      }
    }
    setReviewSaving(true);
    setReviewError("");
    try {
      await api("/api/review/items", {
        method: "POST",
        body: JSON.stringify({
          question: stripMarkdown(reviewDraft.question),
          answer: isChoice ? reviewDraft.correctAnswer : stripMarkdown(reviewDraft.answer),
          explanation: stripMarkdown(reviewDraft.explanation),
          course: reviewDraft.course,
          chapter: reviewDraft.chapter,
          source: reviewDraft.source,
          options: isChoice ? reviewDraft.options.map(stripMarkdown) : []
        })
      });
      if (reviewTargetKey) {
        setReviewSaved((prev) => ({ ...prev, [reviewTargetKey]: true }));
      }
      setReviewDraft(null);
      setReviewTargetKey(null);
    } catch (err: unknown) {
      setReviewError(err instanceof Error ? err.message : "加入错题本失败");
    } finally {
      setReviewSaving(false);
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
                    {message.role === "assistant" && message.citations && message.citations.length > 0 && (
                      <div className="citations">
                        <span className="citations-label">依据</span>
                        {message.citations.map((citation) => (
                          <button
                            className={`citation-chip ${citation.type}`}
                            key={`${message.key}-${citation.label}`}
                            onClick={() => void openCitation(citation)}
                            title={citation.snippet || citation.title || citation.filename || ""}
                          >
                            {citation.type === "web" ? <ExternalLink size={11} /> : <FileText size={11} />}
                            {citation.label}
                            {citation.filename ? ` · ${citation.filename}` : ""}
                            {citation.location ? ` · ${citation.location}` : ""}
                          </button>
                        ))}
                      </div>
                    )}
                    {message.role === "assistant" && message.content && !message.pending && (
                      <div className={`message-actions ${mode === "study" ? "always" : ""}`}>
                        <button onClick={() => copy(message.content)}>
                          <Copy size={11} style={{ marginRight: 4 }} />
                          复制
                        </button>
                        {mode === "study" && (
                          <button
                            className={reviewSaved[message.key] ? "review-add saved" : "review-add"}
                            onClick={() => openReviewDraft(message)}
                          >
                            <BookmarkPlus size={11} style={{ marginRight: 4 }} />
                            {reviewSaved[message.key] ? "已加入错题本" : "加入错题本"}
                          </button>
                        )}
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
                  className={`stage-chip ${stage === item.key && !feynman ? "active" : ""}`}
                  disabled={feynman}
                  onClick={() => setStage(item.key)}
                >
                  {item.label}
                </button>
              ))}
              <span className="stage-divider" />
              <button
                className={`stage-chip feynman ${feynman ? "active" : ""}`}
                onClick={() => {
                  setFeynman((value) => !value);
                  setStage("auto");
                }}
                title="费曼模式：让你先用自己的话讲，我来找漏洞"
              >
                费曼
              </button>
            </div>
          )}
          <div className="composer-box">
            <textarea
              ref={textareaRef}
              value={input}
              rows={1}
              placeholder={
                feynman
                  ? "用你自己的话讲一遍这个概念，我来找漏洞…"
                  : question
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

      {preview && (
        <div className="modal-backdrop" onClick={() => setPreview(null)}>
          <div className="modal citation-modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <div>
                <h3>{preview.filename || preview.title || preview.label}</h3>
                <p className="faint">
                  {preview.course} {preview.chapter} {preview.location}
                </p>
              </div>
              <button className="icon-btn" onClick={() => setPreview(null)} aria-label="关闭">
                <X size={15} />
              </button>
            </div>
            <p className="citation-snippet">{preview.snippet || "这条引用没有可预览的片段。"}</p>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setPreview(null)}>
                关闭
              </button>
              {preview.document_id && (
                <button className="btn" onClick={() => void openNoteFile(preview)}>
                  <FileText size={14} /> 打开原文件
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {reviewDraft && (
        <div className="modal-backdrop" onClick={() => setReviewDraft(null)}>
          <div className="modal review-save-modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <div>
                <h3>加入错题本</h3>
                <p className="faint">保存成一张复习卡，之后在错题本按 3 / 7 / 14 / 30 天复习。</p>
              </div>
              <button className="icon-btn" onClick={() => setReviewDraft(null)} aria-label="关闭">
                <X size={15} />
              </button>
            </div>

            {reviewError && <div className="error-banner">{reviewError}</div>}

            <div className="tab-row" style={{ marginBottom: 12 }}>
              <button
                className={`tab ${reviewDraft.kind === "recall" ? "active" : ""}`}
                onClick={() => setReviewDraft({ ...reviewDraft, kind: "recall" })}
              >
                回忆卡
              </button>
              <button
                className={`tab ${reviewDraft.kind === "choice" ? "active" : ""}`}
                onClick={() => setReviewDraft({ ...reviewDraft, kind: "choice" })}
              >
                选择题
              </button>
            </div>

            <label className="field-label">题目</label>
            <textarea
              className="field-input review-textarea"
              rows={5}
              value={reviewDraft.question}
              onChange={(event) => setReviewDraft({ ...reviewDraft, question: event.target.value })}
            />

            {reviewDraft.kind === "recall" ? (
              <>
                <label className="field-label">参考答案（可留空，自己回忆时用）</label>
                <textarea
                  className="field-input review-textarea"
                  rows={4}
                  value={reviewDraft.answer}
                  onChange={(event) => setReviewDraft({ ...reviewDraft, answer: event.target.value })}
                />
              </>
            ) : (
              <>
                <label className="field-label">选项（A–D 都要填）</label>
                <div className="choice-edit-grid">
                  {reviewDraft.options.map((option, index) => (
                    <label className="choice-edit-row" key={LETTERS[index]}>
                      <b>{LETTERS[index]}</b>
                      <input
                        className="field-input"
                        value={option}
                        onChange={(event) => {
                          const options = [...reviewDraft.options];
                          options[index] = event.target.value;
                          setReviewDraft({ ...reviewDraft, options });
                        }}
                        placeholder={`选项 ${LETTERS[index]}`}
                      />
                    </label>
                  ))}
                </div>
                <label className="field-label">正确答案</label>
                <select
                  className="field-input"
                  value={reviewDraft.correctAnswer}
                  onChange={(event) =>
                    setReviewDraft({ ...reviewDraft, correctAnswer: event.target.value })
                  }
                >
                  <option value="">请选择</option>
                  {LETTERS.map((letter) => (
                    <option value={letter} key={letter}>
                      {letter}
                    </option>
                  ))}
                </select>
              </>
            )}

            <label className="field-label">解析（可留空）</label>
            <textarea
              className="field-input review-textarea"
              rows={3}
              value={reviewDraft.explanation}
              onChange={(event) => setReviewDraft({ ...reviewDraft, explanation: event.target.value })}
            />

            <div className="review-save-row">
              <div>
                <label className="field-label">科目</label>
                <input
                  className="field-input"
                  value={reviewDraft.course}
                  onChange={(event) => setReviewDraft({ ...reviewDraft, course: event.target.value })}
                />
              </div>
              <div>
                <label className="field-label">章节（可选）</label>
                <input
                  className="field-input"
                  value={reviewDraft.chapter}
                  onChange={(event) => setReviewDraft({ ...reviewDraft, chapter: event.target.value })}
                  placeholder="例如：第 3 章 动态规划"
                />
              </div>
            </div>

            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setReviewDraft(null)}>
                取消
              </button>
              <button className="btn primary" onClick={() => void saveReview()} disabled={reviewSaving}>
                <BookmarkPlus size={14} /> {reviewSaving ? "保存中…" : "保存到错题本"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
