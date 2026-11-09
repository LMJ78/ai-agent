import type { AuthResponse, ChatStreamEvent, Citation, User } from "../types";

const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

export const TOKEN_KEY = "ai_agent_token";
export const USER_KEY = "ai_agent_user";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function getStoredUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function saveAuth(data: AuthResponse): void {
  localStorage.setItem(TOKEN_KEY, data.access_token);
  localStorage.setItem(USER_KEY, JSON.stringify(data.user));
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

async function readError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") return data.detail;
    if (Array.isArray(data?.detail)) {
      return data.detail.map((item: { msg?: string }) => item.msg || "参数错误").join("；");
    }
    return JSON.stringify(data);
  } catch {
    return `请求失败（HTTP ${res.status}）`;
  }
}

export async function api<T>(
  path: string,
  options: RequestInit & { token?: string | null } = {}
): Promise<T> {
  const { token = getToken(), headers, ...rest } = options;
  const finalHeaders = new Headers(headers);
  if (token) finalHeaders.set("Authorization", `Bearer ${token}`);
  if (rest.body && !(rest.body instanceof FormData) && !finalHeaders.has("Content-Type")) {
    finalHeaders.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE}${path}`, { ...rest, headers: finalHeaders });
  if (!res.ok) throw new ApiError(res.status, await readError(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function login(username: string, password: string): Promise<AuthResponse> {
  return api<AuthResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
    token: null
  });
}

export async function register(payload: {
  username: string;
  password: string;
  display_name: string;
  invite_code: string;
}): Promise<AuthResponse> {
  return api<AuthResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
    token: null
  });
}

export async function me(): Promise<User> {
  return api<User>("/api/auth/me");
}

export type ChatPayload = {
  message: string;
  session_id?: number | null;
  mode: "study" | "life";
  course?: string;
  question_id?: number;
  teaching_stage?: "hint" | "step" | "answer";
  feynman?: boolean;
};

type StreamHandlers = {
  onSession?: (id: number, course?: string) => void;
  onDelta?: (delta: string) => void;
  onTool?: (event: Extract<ChatStreamEvent, { type: "tool_call" | "tool_result" }>) => void;
  onCitations?: (citations: Citation[]) => void;
  onError?: (message: string) => void;
};

export async function streamChat(
  payload: ChatPayload,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`
    },
    body: JSON.stringify(payload),
    signal
  });

  if (!res.ok) {
    throw new ApiError(res.status, await readError(res));
  }
  if (!res.body) throw new ApiError(500, "浏览器不支持流式响应");

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  const handleBlock = (block: string) => {
    const data = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim())
      .join("\n");
    if (!data || data === "[DONE]") return;
    let event: ChatStreamEvent;
    try {
      event = JSON.parse(data) as ChatStreamEvent;
    } catch {
      return;
    }
    if ("session_id" in event) {
      handlers.onSession?.(event.session_id, event.course);
    } else if ("delta" in event) {
      handlers.onDelta?.(event.delta);
    } else if ("error" in event) {
      handlers.onError?.(event.error);
    } else if ("type" in event && event.type === "citations") {
      handlers.onCitations?.(event.citations);
    } else if ("type" in event) {
      handlers.onTool?.(event);
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || "";
    blocks.forEach(handleBlock);
  }
  buffer += decoder.decode();
  if (buffer.trim()) handleBlock(buffer);
}
