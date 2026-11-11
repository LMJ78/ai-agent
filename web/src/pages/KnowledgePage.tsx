import { useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  ChevronDown,
  Download,
  FileText,
  FolderOpen,
  LoaderCircle,
  Trash2,
  UploadCloud,
  X
} from "lucide-react";
import { ApiError, api, getToken } from "../lib/api";
import type { CourseSummary, DocumentItem } from "../types";

type Props = {
  courses: CourseSummary[];
  onChanged: () => void;
  notify: (message: string, kind?: "ok" | "error") => void;
};

type PreviewState = {
  doc: DocumentItem;
  kind: "pdf" | "text" | "none";
  loading: boolean;
  url?: string;
  text?: string;
  error?: string;
  page?: number;
  pageCount?: number;
};

export function KnowledgePage({ courses, onChanged, notify }: Props) {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [course, setCourse] = useState("算法设计与分析");
  const [chapter, setChapter] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [pdfZoom, setPdfZoom] = useState(1);
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});
  const inputRef = useRef<HTMLInputElement>(null);
  const previewUrlRef = useRef("");

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

  useEffect(() => {
    return () => {
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    };
  }, []);

  const groups = useMemo(() => {
    const map = new Map<string, DocumentItem[]>();
    for (const doc of documents) {
      const name = doc.course?.trim() || "未分类";
      const list = map.get(name) || [];
      list.push(doc);
      map.set(name, list);
    }
    return [...map.entries()]
      .sort(([a], [b]) => a.localeCompare(b, "zh-CN"))
      .map(([name, items]) => [
        name,
        [...items].sort((a, b) => a.filename.localeCompare(b.filename, "zh-CN"))
      ] as const);
  }, [documents]);

  const closePreview = () => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = "";
    }
    setPreview(null);
  };

  const errorText = async (res: Response) => {
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") return data.detail;
    } catch {
      // ignore
    }
    return `打开失败（HTTP ${res.status}）`;
  };

  const loadPdfPage = async (doc: DocumentItem, page: number) => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = "";
    }
    setPreview((current) => ({
      doc,
      kind: "pdf",
      loading: true,
      url: current?.doc.id === doc.id ? current.url : undefined,
      page,
      pageCount: current?.doc.id === doc.id ? current.pageCount : 0,
      error: undefined
    }));

    try {
      const res = await fetch(`/api/documents/${doc.id}/page?page=${page}&width=1600`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      if (!res.ok) throw new Error(await errorText(res));

      const pageCount = Number(res.headers.get("X-Page-Count") || "0") || 1;
      const url = URL.createObjectURL(await res.blob());
      previewUrlRef.current = url;
      setPreview({ doc, kind: "pdf", loading: false, url, page, pageCount });
    } catch (err: unknown) {
      setPreview({
        doc,
        kind: "pdf",
        loading: false,
        page,
        error: err instanceof Error ? err.message : "打开失败"
      });
    }
  };

  const openPreview = async (doc: DocumentItem) => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = "";
    }
    setPdfZoom(1);

    if (doc.preview_kind === "none") {
      setPreview({ doc, kind: "none", loading: false });
      return;
    }

    if (doc.preview_kind === "pdf") {
      await loadPdfPage(doc, 1);
      return;
    }

    setPreview({ doc, kind: "text", loading: true });
    try {
      const res = await fetch(`/api/documents/${doc.id}/preview`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      if (!res.ok) throw new Error(await errorText(res));
      setPreview({ doc, kind: "text", loading: false, text: await res.text() });
    } catch (err: unknown) {
      setPreview({
        doc,
        kind: "text",
        loading: false,
        error: err instanceof Error ? err.message : "打开失败"
      });
    }
  };

  const download = async (doc: DocumentItem) => {
    try {
      const res = await fetch(`/api/documents/${doc.id}/file`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      if (!res.ok) throw new Error(await errorText(res));
      const url = URL.createObjectURL(await res.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = doc.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err: unknown) {
      notify(err instanceof Error ? err.message : "下载失败", "error");
    }
  };

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

  const toggleGroup = (name: string) => {
    setCollapsedGroups((current) => ({ ...current, [name]: !current[name] }));
  };

  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <div>
            <h1>知识库</h1>
            <p>按科目归好类；点「打开」直接看 PDF，PPTX 有配套 PDF 时自动用 PDF 预览。</p>
          </div>
          <span className="badge">
            {documents.length} 份资料 · {groups.length} 个科目
          </span>
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
              <div className="knowledge-groups">
                {groups.map(([groupCourse, items]) => {
                  const isCollapsed = !!collapsedGroups[groupCourse];
                  return (
                    <section className="knowledge-group" key={groupCourse}>
                      <button
                        type="button"
                        className="knowledge-group-head"
                        onClick={() => toggleGroup(groupCourse)}
                        aria-expanded={!isCollapsed}
                      >
                        <span className="knowledge-group-title">
                          <FolderOpen size={16} />
                          <strong>{groupCourse}</strong>
                          <span className="badge">{items.length} 份</span>
                        </span>
                        <ChevronDown
                          size={16}
                          className={isCollapsed ? "knowledge-chevron collapsed" : "knowledge-chevron"}
                        />
                      </button>

                      {!isCollapsed ? (
                        <div className="list knowledge-group-list">
                          {items.map((doc) => (
                            <div className="file-row" key={doc.id}>
                              <div className="file-icon">
                                <FileText size={17} />
                              </div>
                              <div className="file-main">
                                <div className="file-name" title={doc.filename}>
                                  {doc.filename}
                                </div>
                                <div className="file-sub">
                                  {doc.chapter ? `${doc.chapter} · ` : ""}
                                  {doc.chunks} 个片段 · {new Date(doc.created_at).toLocaleDateString()}
                                </div>
                              </div>
                              <span className={`badge ${doc.status === "ready" ? "ok" : ""}`}>{doc.status}</span>
                              {doc.is_shared ? <span className="badge">公共</span> : null}
                              <div className="file-actions">
                                <button
                                  type="button"
                                  className="file-action"
                                  onClick={() => void openPreview(doc)}
                                  title={doc.preview_kind === "pdf" ? "打开 PDF 预览" : "打开资料"}
                                >
                                  <BookOpen size={14} />
                                  <span>{doc.preview_kind === "pdf" ? "打开" : doc.preview_kind === "text" ? "阅读" : "查看"}</span>
                                </button>
                                <button
                                  type="button"
                                  className="icon-btn"
                                  onClick={() => void download(doc)}
                                  title="下载原文件"
                                >
                                  <Download size={14} />
                                </button>
                                {!doc.is_shared ? (
                                  <button
                                    type="button"
                                    className="icon-btn"
                                    onClick={() => void remove(doc)}
                                    title="删除"
                                  >
                                    <Trash2 size={14} />
                                  </button>
                                ) : null}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </section>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      {preview ? (
        <div className="modal-backdrop" onClick={closePreview}>
          <div
            className="knowledge-preview"
            role="dialog"
            aria-modal="true"
            aria-label={preview.doc.filename}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="knowledge-preview-head">
              <div className="knowledge-preview-title">
                <strong title={preview.doc.filename}>{preview.doc.filename}</strong>
                <span>
                  {preview.doc.course}
                  {preview.doc.chapter ? ` · ${preview.doc.chapter}` : ""}
                  {preview.kind === "pdf" && preview.doc.preview_name !== preview.doc.filename
                    ? ` · PDF 版：${preview.doc.preview_name}`
                    : ""}
                </span>
              </div>
              <div className="row">
                <button type="button" className="btn" onClick={() => void download(preview.doc)}>
                  <Download size={14} /> 下载原文件
                </button>
                <button type="button" className="icon-btn" onClick={closePreview} title="关闭">
                  <X size={18} />
                </button>
              </div>
            </div>

            <div className="knowledge-preview-body">
              {preview.loading ? (
                <div className="knowledge-preview-center">
                  <LoaderCircle className="spin" size={20} />
                  <span>正在打开…</span>
                </div>
              ) : preview.error ? (
                <div className="knowledge-preview-center knowledge-preview-error">{preview.error}</div>
              ) : preview.kind === "pdf" ? (
                <div className="pdf-viewer">
                  <div className="pdf-toolbar">
                    <button
                      type="button"
                      className="btn"
                      disabled={preview.loading || (preview.page || 1) <= 1}
                      onClick={() => void loadPdfPage(preview.doc, (preview.page || 1) - 1)}
                    >
                      上一页
                    </button>
                    <span className="pdf-page-count">
                      第 {preview.page || 1} / {preview.pageCount || "…"} 页
                    </span>
                    <button
                      type="button"
                      className="btn"
                      disabled={preview.loading || (preview.page || 1) >= (preview.pageCount || 1)}
                      onClick={() => void loadPdfPage(preview.doc, (preview.page || 1) + 1)}
                    >
                      下一页
                    </button>
                    <span className="pdf-zoom">
                      <button
                        type="button"
                        className="icon-btn"
                        title="缩小"
                        onClick={() => setPdfZoom((value) => Math.max(0.75, Number((value - 0.25).toFixed(2))))}
                      >
                        −
                      </button>
                      <button
                        type="button"
                        className="icon-btn"
                        title="放大"
                        onClick={() => setPdfZoom((value) => Math.min(3, Number((value + 0.25).toFixed(2))))}
                      >
                        +
                      </button>
                    </span>
                  </div>
                  <div className="pdf-canvas">
                    {preview.url ? (
                      <img src={preview.url} alt={`第 ${preview.page || 1} 页`} style={{ width: `${pdfZoom * 100}%` }} />
                    ) : null}
                    {preview.loading ? (
                      <div className="pdf-loading">
                        <LoaderCircle className="spin" size={20} />
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : preview.kind === "text" ? (
                <pre>{preview.text}</pre>
              ) : (
                <div className="knowledge-preview-center">
                  <FileText size={28} />
                  <strong>这个格式浏览器不能直接预览</strong>
                  <p>
                    课程 PPTX 如果有配套 PDF 会自动预览；这份没有配套 PDF，下载后用 WPS/Office 打开即可。
                  </p>
                  <button type="button" className="btn primary" onClick={() => void download(preview.doc)}>
                    <Download size={14} /> 下载原文件
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
