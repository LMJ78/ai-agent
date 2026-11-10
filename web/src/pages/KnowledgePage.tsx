import { useEffect, useRef, useState } from "react";
import { FileText, LoaderCircle, Trash2, UploadCloud } from "lucide-react";
import { ApiError, api } from "../lib/api";
import type { CourseSummary, DocumentItem } from "../types";

type Props = {
  courses: CourseSummary[];
  onChanged: () => void;
  notify: (message: string, kind?: "ok" | "error") => void;
};

export function KnowledgePage({ courses, onChanged, notify }: Props) {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [course, setCourse] = useState("算法设计与分析");
  const [chapter, setChapter] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = async () => {
    setLoading(true);
    try {
      setDocuments(await api<DocumentItem[]>("/api/documents"));
    } catch (err: unknown) {
      notify(err instanceof Error ? err.message : "加载知识库失败", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const upload = async () => {
    if (!file || uploading) return;
    if (!course.trim()) {
      notify("先选一个科目", "error");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("course", course.trim());
    form.append("chapter", chapter.trim());
    setUploading(true);
    try {
      const result = await api<{ chunks: number; filename: string }>("/api/documents", {
        method: "POST",
        body: form
      });
      notify(`「${result.filename}」已入库，切成 ${result.chunks} 个片段`);
      setFile(null);
      setChapter("");
      if (inputRef.current) inputRef.current.value = "";
      await load();
      onChanged();
    } catch (err: unknown) {
      notify(
        err instanceof ApiError ? err.message : err instanceof Error ? err.message : "上传失败",
        "error"
      );
    } finally {
      setUploading(false);
    }
  };

  const remove = async (doc: DocumentItem) => {
    if (!window.confirm(`删除「${doc.filename}」？它会从检索里移除。`)) return;
    try {
      await api(`/api/documents/${doc.id}`, { method: "DELETE" });
      notify("资料已删除");
      await load();
      onChanged();
    } catch (err: unknown) {
      notify(err instanceof Error ? err.message : "删除失败", "error");
    }
  };

  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <div>
            <h1>知识库</h1>
            <p>上传课件、讲义或笔记，聊天时会优先从这些资料里找依据。</p>
          </div>
          <span className="badge">{documents.length} 份资料</span>
        </div>

        <div className="knowledge-layout">
          <div className="card">
            <div className="row" style={{ marginBottom: 14 }}>
              <UploadCloud size={17} />
              <strong style={{ fontSize: 14 }}>上传新资料</strong>
            </div>

            <div className="form">
              <label
                className="dropzone"
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault();
                  const dropped = event.dataTransfer.files?.[0];
                  if (dropped) setFile(dropped);
                }}
              >
                <input
                  ref={inputRef}
                  type="file"
                  hidden
                  accept=".pdf,.pptx,.docx,.md,.txt"
                  onChange={(event) => setFile(event.target.files?.[0] || null)}
                />
                <strong>{file ? file.name : "点这里选文件，或拖进来"}</strong>
                PDF / PPTX / DOCX / MD / TXT，单个不超过 20MB
              </label>

              <div className="field">
                <label>科目</label>
                <input
                  className="input"
                  list="course-options"
                  value={course}
                  onChange={(event) => setCourse(event.target.value)}
                  placeholder="例如：算法设计与分析"
                />
                <datalist id="course-options">
                  {courses.map((item) => (
                    <option key={item.name} value={item.name} />
                  ))}
                </datalist>
              </div>

              <div className="field">
                <label>章节（可选）</label>
                <input
                  className="input"
                  value={chapter}
                  onChange={(event) => setChapter(event.target.value)}
                  placeholder="例如：第3章 动态规划"
                />
              </div>

              <button className="btn primary" onClick={() => void upload()} disabled={!file || uploading}>
                {uploading ? <LoaderCircle className="spin" size={14} /> : <UploadCloud size={14} />}
                {uploading ? "正在解析入库…" : "上传并入库"}
              </button>
              <p className="faint" style={{ margin: 0, fontSize: 11, lineHeight: 1.6 }}>
                扫描版 PDF 会自动走视觉 OCR，页数多时要等一会儿。
              </p>
            </div>
          </div>

          <div>
            {loading ? (
              <div className="center" style={{ height: 180 }}>
                <LoaderCircle className="spin" size={18} />
              </div>
            ) : documents.length === 0 ? (
              <div className="card" style={{ textAlign: "center", padding: "48px 20px", color: "var(--muted)" }}>
                还没有资料。先传一份课件，问问题时我就能引用它。
              </div>
            ) : (
              <div className="list">
                {documents.map((doc) => (
                  <div className="file-row" key={doc.id}>
                    <div className="file-icon">
                      <FileText size={17} />
                    </div>
                    <div className="file-main">
                      <div className="file-name">{doc.filename}</div>
                      <div className="file-sub">
                        {doc.course}
                        {doc.chapter ? ` · ${doc.chapter}` : ""} · {doc.chunks} 个片段 ·{" "}
                        {new Date(doc.created_at).toLocaleDateString()}
                      </div>
                    </div>
                    <span className={`badge ${doc.status === "ready" ? "ok" : ""}`}>{doc.status}</span>
                    {doc.is_shared ? (
                      <span className="badge">公共</span>
                    ) : (
                      <button className="icon-btn" onClick={() => void remove(doc)} title="删除">
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
