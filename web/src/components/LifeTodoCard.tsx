import { useEffect, useState } from "react";
import { Check, ChevronDown, ChevronUp, ListTodo, Loader2, Plus } from "lucide-react";
import { api } from "../lib/api";
import type { TodoItem } from "../types";

type Scope = "today" | "all";

function todayAtEnd(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day} 23:59`;
}

function shortDue(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export function LifeTodoCard() {
  const [scope, setScope] = useState<Scope>("today");
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState("");
  const [adding, setAdding] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState("");

  const load = async (nextScope: Scope) => {
    setLoading(true);
    setError("");
    try {
      const data = await api<TodoItem[]>(`/api/todos?status=pending&period=${nextScope}`);
      setTodos(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "待办加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(scope);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);

  const addTodo = async () => {
    const title = draft.trim();
    if (!title || adding) return;
    setAdding(true);
    setError("");
    try {
      await api<TodoItem>("/api/todos", {
        method: "POST",
        body: JSON.stringify({ title, due_at: todayAtEnd() })
      });
      setDraft("");
      await load(scope);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "添加失败");
    } finally {
      setAdding(false);
    }
  };

  const completeTodo = async (todo: TodoItem) => {
    if (busyId != null) return;
    setBusyId(todo.id);
    setError("");
    try {
      await api<TodoItem>(`/api/todos/${todo.id}`, {
        method: "PATCH",
        body: JSON.stringify({ done: true })
      });
      setTodos((prev) => prev.filter((item) => item.id !== todo.id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "完成失败");
    } finally {
      setBusyId(null);
    }
  };

  const toggleScope = () => setScope((prev) => (prev === "today" ? "all" : "today"));

  return (
    <section className="life-todos" aria-label="今日待办">
      <div className="life-todos-head">
        <span className="life-todos-title">
          <ListTodo size={14} /> {scope === "today" ? "今日待办" : "全部待办"}
        </span>
        <span className="life-todos-count">{todos.length}</span>
        <button className="life-todos-toggle" onClick={toggleScope} title={scope === "today" ? "查看全部" : "只看今天"}>
          {scope === "today" ? "全部" : "今天"}
          {scope === "today" ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
        </button>
      </div>

      <div className="life-todo-add">
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void addTodo();
            }
          }}
          placeholder="加一件今天要做的事"
          maxLength={255}
        />
        <button onClick={() => void addTodo()} disabled={!draft.trim() || adding} title="添加待办">
          {adding ? <Loader2 size={14} className="spin" /> : <Plus size={15} />}
        </button>
      </div>

      {error && <div className="life-todo-error">{error}</div>}

      <div className="life-todo-list">
        {loading && (
          <div className="life-todo-empty">
            <Loader2 size={14} className="spin" /> 加载中…
          </div>
        )}
        {!loading && todos.length === 0 && (
          <div className="life-todo-empty">
            {scope === "today" ? "今天还没有待办，先加一件。" : "还没有未完成的待办。"}
          </div>
        )}
        {!loading &&
          todos.map((todo) => (
            <div className="life-todo-item" key={todo.id}>
              <button
                className="life-todo-check"
                onClick={() => void completeTodo(todo)}
                disabled={busyId === todo.id}
                aria-label={`完成：${todo.title}`}
              >
                {busyId === todo.id ? <Loader2 size={11} className="spin" /> : <Check size={11} />}
              </button>
              <div className="life-todo-body">
                <div className="life-todo-text">{todo.title}</div>
                {todo.due_at && <div className="life-todo-due">{shortDue(todo.due_at)} 截止</div>}
              </div>
            </div>
          ))}
      </div>
    </section>
  );
}
