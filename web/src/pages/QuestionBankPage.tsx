import { useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  Camera,
  Check,
  FileText,
  Image as ImageIcon,
  LoaderCircle,
  Plus,
  Trash2,
  X
} from "lucide-react";
import { ApiError, api } from "../lib/api";
import { useAuthedImage } from "../lib/useAuthedImage";
import type { CourseSummary, QuestionItem } from "../types";

type Props = {
  courses: CourseSummary[];
  onAsk: (question: QuestionItem) => void;
  notify: (message: string, kind?: "ok" | "error") => void;
  onChanged: () => void;
};

function QuestionCard({
  question,
  onOpen
}: {
  question: QuestionItem;
  onOpen: (question: QuestionItem) => void;
}) {
  const image = useAuthedImage(
    question.has_file && question.source_type === "image"
      ? `/api/questions/${question.id}/file`
      : null
  );

  return (
    <button className="question-card" onClick={() => onOpen(question)}>
      <div className="question-thumb">
        {image ? (
          <img src={image} alt={question.original_filename || "题目原图"} />
        ) : question.source_type === "image" ? (
          <ImageIcon size={22} />
        ) : (
          <FileText size={22} />
        )}
      </div>
      <div className="question-body">
        <div className="question-title">{question.parsed_text || "（还没有识别出题干）"}</div>
        <div className="question-meta">
          <span className="badge">{question.course || "未分类"}</span>
          {question.chapter && <span>{question.chapter}</span>}
          <span className={`badge ${question.status === "confirmed" ? "ok" : "warn"}`}>
            {question.status === "confirmed" ? "已确认" : "待确认"}
          </span>
        </div>
      </div>
    </button>
  );
}

export function QuestionBankPage({ courses, onAsk, notify, onChanged }: Props) {
  const [questions, setQuestions] = useState<QuestionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [courseFilter, setCourseFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [detail, setDetail] = useState<QuestionItem | null>(null);
  const [editText, setEditText] = useState("");
  const [saving, setSaving] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createTab, setCreateTab] = useState<"text" | "file">("file");
  const [newText, setNewText] = useState("");
  const [newFile, setNewFile] = useState<File | null>(null);
  const [newCourse, setNewCourse] = useState("算法设计与分析");
  const [newChapter, setNewChapter] = useState("");
  const [creating, setCreating] = useState(false);

  const image = useAuthedImage(
    detail?.has_file && detail.source_type === "image" ? `/api/questions/${detail.id}/file` : null
  );

  const load = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (courseFilter) params.set("course", courseFilter);
      if (sourceFilter) params.set("source_type", sourceFilter);
      params.set("limit", "100");
      setQuestions(await api<QuestionItem[]>(`/api/questions?${params.toString()}`));
    } catch (err: unknown) {
      notify(err instanceof Error ? err.message : "加载题库失败", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [courseFilter, sourceFilter]);

  const coursesWithQuestions = useMemo(() => {
    const names = new Set(courses.map((item) => item.name));
    questions.forEach((item) => names.add(item.course));
    return Array.from(names).filter(Boolean);
  }, [courses, questions]);

  const openDetail = (question: QuestionItem) => {
    setDetail(question);
    setEditText(question.parsed_text);
  };

  const confirm = async () => {
    if (!detail || saving) return;
    if (!editText.trim()) {
      notify("题干不能为空", "error");
      return;
    }
    setSaving(true);
    try {
      const updated = await api<QuestionItem>(`/api/questions/${detail.id}/confirm`, {
        method: "POST",
        body: JSON.stringify({ text: editText.trim() })
      });
      setDetail(updated);
      setQuestions((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      notify("题目已确认，可以开始讲解");
      onChanged();
    } catch (err: unknown) {
      notify(err instanceof ApiError ? err.message : "确认失败", "error");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (question: QuestionItem) => {
    if (!window.confirm("删除这道题？原图/原文件也会一起删掉。")) return;
    try {
      await api(`/api/questions/${question.id}`, { method: "DELETE" });
      setQuestions((prev) => prev.filter((item) => item.id !== question.id));
      if (detail?.id === question.id) setDetail(null);
      notify("题目已删除");
      onChanged();
    } catch (err: unknown) {
      notify(err instanceof Error ? err.message : "删除失败", "error");
    }
  };

  const create = async () => {
    if (creating) return;
    if (createTab === "text" && !newText.trim()) {
      notify("先把题目文字贴进来", "error");
      return;
    }
    if (createTab === "file" && !newFile) {
      notify("先选一张图片或文件", "error");
      return;
    }
    setCreating(true);
    try {
      let created: QuestionItem;
      if (createTab === "text") {
        created = await api<QuestionItem>("/api/questions/text", {
          method: "POST",
          body: JSON.stringify({ text: newText.trim(), course: newCourse, chapter: newChapter })
        });
      } else {
        const form = new FormData();
        form.append("file", newFile!);
        form.append("course", newCourse);
        form.append("chapter", newChapter);
        created = await api<QuestionItem>("/api/questions/upload", {
          method: "POST",
          body: form
        });
      }
      setCreateOpen(false);
      setNewText("");
      setNewFile(null);
      setNewChapter("");
      setQuestions((prev) => [created, ...prev]);
      openDetail(created);
      notify(created.status === "draft" ? "已转写，核对一下题干再确认" : "题目已保存");
      onChanged();
    } catch (err: unknown) {
      notify(
        err instanceof ApiError ? err.message : err instanceof Error ? err.message : "录入失败",
        "error"
      );
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <div>
            <h1>题库</h1>
            <p>拍照、上传或粘贴的题目都在这里。先确认题干，再让老师按节奏讲。</p>
          </div>
          <button className="btn primary" onClick={() => setCreateOpen(true)}>
            <Plus size={14} /> 录一道题
          </button>
        </div>

        <div className="filters">
          <select className="select" value={courseFilter} onChange={(event) => setCourseFilter(event.target.value)}>
            <option value="">全部科目</option>
            {coursesWithQuestions.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <select className="select" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}>
            <option value="">全部来源</option>
            <option value="image">拍照/截图</option>
            <option value="pdf">PDF</option>
            <option value="pptx">PPTX</option>
            <option value="docx">Word</option>
            <option value="text">粘贴文字</option>
          </select>
          <span className="spacer" />
          <span className="faint" style={{ fontSize: 11 }}>
            共 {questions.length} 道
          </span>
        </div>

        {loading ? (
          <div className="center" style={{ height: 200 }}>
            <LoaderCircle className="spin" size={18} />
          </div>
        ) : questions.length === 0 ? (
          <div className="card" style={{ textAlign: "center", padding: "60px 20px", color: "var(--muted)" }}>
            <Camera size={26} style={{ marginBottom: 12 }} />
            <div>还没有题目。点右上角「录一道题」，拍一张或传个文件。</div>
          </div>
        ) : (
          <div className="grid">
            {questions.map((question) => (
              <QuestionCard key={question.id} question={question} onOpen={openDetail} />
            ))}
          </div>
        )}
      </div>

      {createOpen && (
        <div className="overlay" onClick={() => setCreateOpen(false)}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <h2>录一道题</h2>
              <button className="icon-btn" onClick={() => setCreateOpen(false)}>
                <X size={17} />
              </button>
            </div>

            <div className="login-tabs" style={{ marginBottom: 14 }}>
              <button className={createTab === "file" ? "active" : ""} onClick={() => setCreateTab("file")}>
                拍照 / 文件
              </button>
              <button className={createTab === "text" ? "active" : ""} onClick={() => setCreateTab("text")}>
                粘贴文字
              </button>
            </div>

            <div className="form">
              <div className="field">
                <label>科目</label>
                <input
                  className="input"
                  list="question-course-options"
                  value={newCourse}
                  onChange={(event) => setNewCourse(event.target.value)}
                />
                <datalist id="question-course-options">
                  {coursesWithQuestions.map((name) => (
                    <option key={name} value={name} />
                  ))}
                </datalist>
              </div>
              <div className="field">
                <label>章节（可选）</label>
                <input
                  className="input"
                  value={newChapter}
                  onChange={(event) => setNewChapter(event.target.value)}
                  placeholder="例如：第3章 动态规划"
                />
              </div>

              {createTab === "file" ? (
                <label
                  className="dropzone"
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={(event) => {
                    event.preventDefault();
                    const dropped = event.dataTransfer.files?.[0];
                    if (dropped) setNewFile(dropped);
                  }}
                >
                  <input
                    type="file"
                    hidden
                    accept=".jpg,.jpeg,.png,.webp,.pdf,.pptx,.docx,.md,.txt"
                    onChange={(event) => setNewFile(event.target.files?.[0] || null)}
                  />
                  <strong>{newFile ? newFile.name : "点这里选图片或文件"}</strong>
                  图片会先转写成文字；PDF / PPTX / DOCX 会抽文字
                </label>
              ) : (
                <textarea
                  className="input"
                  rows={8}
                  value={newText}
                  onChange={(event) => setNewText(event.target.value)}
                  placeholder="把题目完整贴进来，包括选项和已知条件…"
                  style={{ resize: "vertical", lineHeight: 1.7 }}
                />
              )}

              <button className="btn primary" onClick={() => void create()} disabled={creating}>
                {creating ? <LoaderCircle className="spin" size={14} /> : <Plus size={14} />}
                {creating ? "正在识别…" : "保存为草稿"}
              </button>
            </div>
          </div>
        </div>
      )}

      {detail && (
        <div className="overlay" onClick={() => setDetail(null)}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <h2>
                {detail.course || "未分类"}
                {detail.chapter ? ` · ${detail.chapter}` : ""}
              </h2>
              <button className="icon-btn" onClick={() => setDetail(null)}>
                <X size={17} />
              </button>
            </div>

            {image && <img className="question-image" src={image} alt="题目原图" />}

            <div className="row" style={{ marginBottom: 8 }}>
              <span className={`badge ${detail.status === "confirmed" ? "ok" : "warn"}`}>
                {detail.status === "confirmed" ? "已确认" : "待确认"}
              </span>
              <span className="badge">{detail.source_type}</span>
              {detail.original_filename && <span className="faint" style={{ fontSize: 11 }}>{detail.original_filename}</span>}
            </div>

            <textarea
              className="input"
              rows={10}
              value={editText}
              onChange={(event) => setEditText(event.target.value)}
              style={{ resize: "vertical", lineHeight: 1.7 }}
            />

            <div className="row" style={{ marginTop: 14 }}>
              {detail.status !== "confirmed" && (
                <button className="btn primary" onClick={() => void confirm()} disabled={saving}>
                  {saving ? <LoaderCircle className="spin" size={14} /> : <Check size={14} />}
                  确认题目
                </button>
              )}
              {detail.status === "confirmed" && (
                <button
                  className="btn primary"
                  onClick={() => {
                    onAsk(detail);
                    setDetail(null);
                  }}
                >
                  <BookOpen size={14} /> 让老师讲这道题
                </button>
              )}
              <button className="btn danger" onClick={() => void remove(detail)}>
                <Trash2 size={14} /> 删除
              </button>
              <span className="spacer" />
              <button className="btn" onClick={() => setDetail(null)}>
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
