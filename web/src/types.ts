export type User = {
  id: number;
  username: string;
  display_name: string;
  role: string;
  created_at: string;
};

export type AuthResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
};

export type ChatSession = {
  id: number;
  title: string;
  mode: "study" | "life";
  course: string;
  message_count: number;
  updated_at: string;
};

export type ChatMessage = {
  id?: number;
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string;
  pending?: boolean;
  trace?: ToolTrace[];
};

export type ToolTrace = {
  type: "tool_call" | "tool_result";
  name?: string;
  arguments?: unknown;
  content?: string;
};

export type DocumentItem = {
  id: number;
  filename: string;
  course: string;
  chapter: string;
  status: string;
  chunks: number;
  created_at: string;
};

export type QuestionItem = {
  id: number;
  session_id: number | null;
  course: string;
  chapter: string;
  source_type: string;
  original_text: string;
  parsed_text: string;
  source_path: string;
  original_filename: string;
  has_file: boolean;
  status: "draft" | "confirmed";
  needs_confirmation: boolean;
  created_at: string;
  confirmed_at: string;
};

export type CourseSummary = {
  name: string;
  sessions: number;
  questions: number;
  documents: number;
};

export type TodoItem = {
  id: number;
  title: string;
  due_at: string | null;
  remind_at: string | null;
  reminded_at: string | null;
  done: boolean;
  created_at: string;
};

export type MemoryItem = {
  id: number;
  kind: string;
  content: string;
  created_at: string;
};

export type ChatStreamEvent =
  | { session_id: number; course?: string }
  | { delta: string }
  | { type: "tool_call" | "tool_result"; name?: string; arguments?: unknown; content?: string }
  | { error: string };
