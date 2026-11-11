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

export type Citation = {
  type: "note" | "web";
  label: string;
  title?: string;
  url?: string;
  document_id?: number;
  filename?: string;
  location?: string;
  course?: string;
  chapter?: string;
  snippet?: string;
};

export type ChatMessage = {
  id?: number;
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string;
  pending?: boolean;
  trace?: ToolTrace[];
  citations?: Citation[];
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
  is_shared: boolean;
  preview_kind: "pdf" | "text" | "none";
  preview_name: string;
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
  | { type: "citations"; citations: Citation[] }
  | { error: string };

export type ReviewItem = {
  id: number;
  course: string;
  chapter: string;
  kind: "choice" | "recall";
  question: string;
  options: string[];
  answer: string;
  explanation: string;
  source: string;
  wrong_count: number;
  review_count: number;
  correct_streak: number;
  last_result: string;
  status: "active" | "mastered";
  next_review_at: string | null;
  last_reviewed_at: string | null;
  created_at: string;
};

export type ReviewMastery = {
  course: string;
  chapter: string;
  total: number;
  active: number;
  mastered: number;
  due: number;
  wrong_count: number;
  best_streak: number;
  mastery: number;
};

export type ReviewPlan = {
  exam_date: string;
  days: number;
  active: number;
  due: number;
  daily_target: number;
  weak_chapters: ReviewMastery[];
  message: string;
};

export type ReviewStats = {
  active: number;
  mastered: number;
  due: number;
  by_course: { course: string; count: number }[];
};

export type CalendarEvent = {
  id: number;
  title: string;
  location: string;
  course: string;
  start_at: string;
  end_at: string | null;
  recurrence: "none" | "weekly";
  weekday: number | null;
  note: string;
  occurrence_start?: string;
  occurrence_end?: string | null;
};

export type CalendarConflict = {
  first: {
    id: number;
    title: string;
    location: string;
    start_at: string;
    end_at: string;
  };
  second: {
    id: number;
    title: string;
    location: string;
    start_at: string;
    end_at: string;
  };
};

export type PushChannelState = {
  provider: string;
  configured: boolean;
  enabled: boolean;
  token_masked: string;
};

export type BriefSettings = {
  morning_enabled: boolean;
  morning_time: string;
  evening_enabled: boolean;
  evening_time: string;
  news_topics: string;
};

export type Habit = {
  id: number;
  name: string;
  icon: string;
  remind_at: string;
  sort_order: number;
  active: boolean;
  done_today: boolean;
  streak: number;
  week_done: number;
};

export type UsageDay = {
  date: string;
  turns: number;
  input_tokens: number;
  output_tokens: number;
  cost_yuan: number;
};

export type UsageSummary = {
  days: number;
  total_turns: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_yuan: number;
  series: UsageDay[];
};

export type NewsItem = {
  id: number;
  title: string;
  summary: string;
  url: string;
  source: string;
  published_at: string;
  read: boolean;
  starred: boolean;
};

export type NewsCategory = {
  name: string;
  items: NewsItem[];
};

export type NewsDay = {
  date: string;
  categories: NewsCategory[];
};

export type NewsResponse = {
  days: NewsDay[];
  retention_days: number;
  warning: string;
};

export type NotificationItem = {
  id: number;
  kind: string;
  title: string;
  body: string;
  link: string;
  read: boolean;
  created_at: string;
};

export type NotificationsResponse = {
  items: NotificationItem[];
  unread: number;
};
