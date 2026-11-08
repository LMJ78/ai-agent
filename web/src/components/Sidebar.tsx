import { useMemo, useState } from "react";
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  GraduationCap,
  Library,
  LogOut,
  MessageSquare,
  Plus,
  Search,
  X
} from "lucide-react";
import type { ChatSession, User } from "../types";

export type PageKey = "chat" | "knowledge" | "questions";

type Props = {
  user: User;
  sessions: ChatSession[];
  activeSessionId: number | null;
  activePage: PageKey;
  open: boolean;
  onClose: () => void;
  onSelectSession: (session: ChatSession) => void;
  onNewChat: () => void;
  onPage: (page: PageKey) => void;
  onLogout: () => void;
};

const PAGE_ITEMS: { key: PageKey; label: string; icon: typeof MessageSquare }[] = [
  { key: "chat", label: "聊天", icon: MessageSquare },
  { key: "knowledge", label: "知识库", icon: Library },
  { key: "questions", label: "题库", icon: BookOpen }
];

function formatSessionDate(iso: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) return "今天";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "昨天";
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}

export function Sidebar({
  user,
  sessions,
  activeSessionId,
  activePage,
  open,
  onClose,
  onSelectSession,
  onNewChat,
  onPage,
  onLogout
}: Props) {
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const groups = useMemo(() => {
    const map = new Map<string, ChatSession[]>();
    const keyword = query.trim().toLowerCase();
    for (const session of sessions) {
      if (
        keyword &&
        !session.title.toLowerCase().includes(keyword) &&
        !session.course.toLowerCase().includes(keyword)
      ) {
        continue;
      }
      const course = session.course || "未分类";
      const list = map.get(course) || [];
      list.push(session);
      map.set(course, list);
    }
    return Array.from(map.entries()).sort((a, b) => {
      if (a[0] === "未分类") return 1;
      if (b[0] === "未分类") return -1;
      return b[1].length - a[1].length;
    });
  }, [sessions, query]);

  const initial = (user.display_name || user.username || "?").slice(0, 1).toUpperCase();

  return (
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className="sidebar-head">
        <div className="brand">
          <div className="brand-mark">伴</div>
          <div>
            <div className="brand-name">伴学</div>
            <div className="brand-sub">AI 学习与生活助手</div>
          </div>
          <button className="icon-btn sidebar-close" style={{ marginLeft: "auto" }} onClick={onClose} aria-label="关闭侧边栏">
            <X size={16} />
          </button>
        </div>

        <button className="new-chat" onClick={onNewChat}>
          <Plus size={16} /> 新建对话
        </button>

        <label className="search-box">
          <Search size={14} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索会话"
          />
        </label>
      </div>

      <div className="session-groups">
        {groups.length === 0 && (
          <div className="faint" style={{ fontSize: 12, padding: "18px 10px", lineHeight: 1.7 }}>
            还没有会话。点「新建对话」开始，第一条消息会自动成为标题。
          </div>
        )}
        {groups.map(([course, items]) => {
          const isCollapsed = collapsed[course];
          return (
            <div className="course-group" key={course}>
              <button
                className="course-head"
                onClick={() => setCollapsed((prev) => ({ ...prev, [course]: !prev[course] }))}
              >
                {isCollapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
                <GraduationCap size={13} />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {course}
                </span>
                <span className="count">{items.length}</span>
              </button>
              {!isCollapsed && (
                <div className="session-list">
                  {items.map((session) => (
                    <button
                      key={session.id}
                      className={`session-item ${session.id === activeSessionId ? "active" : ""}`}
                      onClick={() => {
                        onSelectSession(session);
                        onClose();
                      }}
                      title={session.title}
                    >
                      {session.title || "未命名对话"}
                      <div className="session-date">
                        {formatSessionDate(session.updated_at)} · {session.message_count} 条
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <nav className="sidebar-nav">
        {PAGE_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.key}
              className={`nav-item ${activePage === item.key ? "active" : ""}`}
              onClick={() => {
                onPage(item.key);
                onClose();
              }}
            >
              <Icon size={15} /> {item.label}
            </button>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <div className="avatar">{initial}</div>
        <div className="user-meta">
          <div className="user-name">{user.display_name || user.username}</div>
          <div className="user-role">@{user.username}</div>
        </div>
        <button className="icon-btn" onClick={onLogout} title="退出登录" aria-label="退出登录">
          <LogOut size={15} />
        </button>
      </div>
    </aside>
  );
}
