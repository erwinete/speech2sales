const TOKEN = () => localStorage.getItem("polylog_token") ?? "dev-insecure-token";

export interface CallFilters {
  days?: number;
  dateFrom?: string;
  dateTo?: string;
  durationMin?: number | null;
  durationMax?: number | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "X-Api-Key": TOKEN(),
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}

export interface CallRow {
  id: string;
  external_id: string | null;
  direction: string;
  phone_from: string | null;
  phone_to: string | null;
  contact_id: string | null;
  started_at: string;
  duration_sec: number | null;
  state: string;
  thread_id: string | null;
  chain_depth: number | null;
}

export interface Segment {
  idx: number;
  speaker: string;
  start_ms: number;
  end_ms: number;
  text: string;
  conf: number | null;
}

export interface ScoreItem {
  item_id: string;
  title: string | null;
  score: number;
  weight: number;
  explanation: string;
  evidence: { ref_id?: string; span: string; start_ms: number | null; method?: string }[];
}

export interface SignalRow {
  kind: string;
  span_text: string;
  start_ms: number | null;
  confidence: number;
  model_id: string;
}

export interface ViolationRow {
  kind: string;
  span_text: string;
  start_ms: number | null;
  model_id: string;
}

export interface CallDetailRow extends CallRow {
  stage_error: { stage: string; error: string } | null;
  channels_map: Record<string, string> | null;
  recording_key: string | null;
  normalized_key: string | null;
  asr_backend_id: string | null;
  avg_conf: number | null;
  segments: Segment[];
  metrics: Record<string, unknown> | null;
  signals: SignalRow[];
  violations: ViolationRow[];
  objections: {
    type: string;
    span_text: string;
    start_ms: number | null;
    response_status: string | null;
    confidence: number;
  }[];
  scores: {
    rubric_id: string;
    rubric_version: number;
    total: number;
    items: ScoreItem[];
    scorer_version: string;
  }[];
}

export interface ContactHit {
  contact_id: string;
  display_name: string | null;
  phones: string[];
  calls_total: number;
  last_call_at: string | null;
  risk_score: number | null;
  risk_band: string | null;
  avg_score: number | null;
  objections_unhandled: number;
  sentiment_last: number | null;
  sentiment_trend: number | null;
}

export interface CardCall {
  id: string;
  direction: string;
  phone_from: string | null;
  phone_to: string | null;
  started_at: string;
  duration_sec: number | null;
  state: string;
  chain_depth: number | null;
  score_total: number | null;
  sentiment: number | null;
  objections: { type: string; response_status: string | null; start_ms: number | null }[];
}

export interface RiskInfo {
  score: number;
  band: string;
  factors: {
    feature: string;
    value: number | null;
    contribution: number;
    description: string;
  }[];
  model_id: string;
}

export interface ContactCard {
  contact: { id: string; display_name: string | null; created_at: string };
  phones: string[];
  company: { id: string; name: string | null; industry: string | null } | null;
  deals: {
    id: string;
    stage: string | null;
    amount: number | null;
    currency: string | null;
    status: string | null;
  }[];
  stats: {
    calls_total: number;
    done_calls: number;
    first_call_at: string | null;
    last_call_at: string | null;
    avg_score: number | null;
    objections_total: number;
    objections_unhandled: number;
    talk_sec_total: number;
    sentiment_last: number | null;
    sentiment_trend: number | null;
  };
  calls: CardCall[];
  interactions: {
    id: string;
    kind: string;
    occurred_at: string;
    payload: Record<string, unknown> | null;
  }[];
  risk: RiskInfo | null;
  repeat: {
    items: { type: string; calls: number; last_status: string | null; last_at: string }[];
  };
  nba: {
    items: { action: string; reason: string }[];
  };
  similar: {
    base_call_id: string;
    items: {
      call_id: string;
      similarity: number;
      phone: string | null;
      started_at: string;
      duration_sec: number | null;
    }[];
  } | null;
}

export const api = {
  listCalls: (f: CallFilters) => {
    const q = new URLSearchParams({ limit: "50" });
    if (f.days && !f.dateFrom && !f.dateTo) q.set("days", String(f.days));
    if (f.dateFrom) q.set("date_from", f.dateFrom);
    if (f.dateTo) q.set("date_to", f.dateTo);
    if (f.durationMin) q.set("duration_min", String(f.durationMin));
    if (f.durationMax) q.set("duration_max", String(f.durationMax));
    return request<{ total: number; items: CallRow[] }>(`/api/v1/calls?${q}`);
  },
  callDetail: (id: string) => request<CallDetailRow>(`/api/v1/calls/${id}`),
  reprocess: (id: string) =>
    request<CallRow>(`/api/v1/calls/${id}/reprocess`, { method: "POST" }),
  artifact: (id: string) => request<Record<string, unknown>>(`/api/v1/calls/${id}/artifact`),
  stats: (f: CallFilters) => {
    const q = new URLSearchParams({ days: String(f.days ?? 30) });
    if (f.dateFrom) q.set("date_from", f.dateFrom);
    if (f.dateTo) q.set("date_to", f.dateTo);
    if (f.durationMin) q.set("duration_min", String(f.durationMin));
    if (f.durationMax) q.set("duration_max", String(f.durationMax));
    return request<{
      total_calls: number;
      done_calls: number;
      avg_score: number | null;
      top_objections: { type: string; count: number }[];
    }>(`/api/v1/stats/summary?${q}`);
  },
  audioUrl: (id: string) => `/api/v1/calls/${id}/audio?api_key=${encodeURIComponent(TOKEN())}`,
  contactCalls: (contactId: string) =>
    request<{ total: number; items: CallRow[] }>(`/api/v1/contacts/${contactId}/calls`),
  similar: (id: string, limit = 5) =>
    request<{
      call_id: string;
      items: {
        call_id: string;
        similarity: number;
        phone: string | null;
        started_at: string;
        duration_sec: number | null;
      }[];
    }>(`/api/v1/search/similar?call_id=${id}&limit=${limit}`),
  risksTop: (limit = 5) =>
    request<{
      items: {
        contact_id: string;
        score: number;
        band: string;
        top_factor: string;
        factors: { feature: string; contribution: number; description: string }[];
        calls_total: number | null;
        recent_call_ids: string[];
      }[];
      total: number;
    }>(`/api/v1/risks/top?limit=${limit}`),
  insights: (status = "new") =>
    request<{
      items: {
        id: string;
        kind: string;
        severity: string;
        contact_id: string | null;
        payload: {
          score?: number;
          band?: string;
          factors?: { feature: string; contribution: number; description: string }[];
          contact_id?: string;
        };
        generated_by: string;
        created_at: string;
      }[];
    }>(`/api/v1/insights?status=${status}`),
  insightAction: (id: string, action: "ack" | "dismiss") =>
    request<{ id: string; status: string }>(`/api/v1/insights/${id}/${action}`, { method: "POST" }),
  clusters: (days = 90) =>
    request<{
      clusters: {
        size: number;
        quotes: string[];
        top_types: [string, number][];
        dominant_type: string | null;
        calls: { call_id: string }[];
      }[];
    }>(`/api/v1/insights/objection-clusters?days=${days}`),
  searchContacts: (q: string | null) => {
    const base = "/api/v1/contacts/search";
    return request<{ items: ContactHit[] }>(
      q ? `${base}?q=${encodeURIComponent(q)}` : base,
    );
  },
  contactCard: (id: string) => request<ContactCard>(`/api/v1/contacts/${id}/card`),

  // ── v2 management ──
  me: () =>
    request<UserProfile>("/api/v1/auth/me"),
  login: (email: string, password: string) =>
    request<{ access_token: string; user: UserProfile }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  listUsers: (params?: { role?: string; team?: string; q?: string; is_active?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.role) qs.set("role", params.role);
    if (params?.team) qs.set("team", params.team);
    if (params?.q) qs.set("q", params.q);
    if (params?.is_active != null) qs.set("is_active", String(params.is_active));
    return request<{ items: UserProfile[]; total: number }>(`/api/v1/users?${qs}`);
  },
  createUser: (body: { email: string; display_name: string; password: string; role: string; team_name?: string; agent_ext_ids?: string[] }) =>
    request<{ id: string; email: string; bound_calls: number }>("/api/v1/users", {
      method: "POST", body: JSON.stringify(body),
    }),
  updateUser: (id: string, body: Record<string, unknown>) =>
    request<{ id: string }>(`/api/v1/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deactivateUser: (id: string) =>
    request<{ id: string }>(`/api/v1/users/${id}`, { method: "DELETE" }),
  voiceprints: () =>
    request<{ items: { agent_key: string; samples: number; model_id: string; created_at: string; user: { display_name: string | null } | null }[] }>("/api/v1/users/voiceprints"),
  deleteVoiceprint: (agentKey: string) =>
    request<{ deleted: boolean }>(`/api/v1/users/voiceprints/${encodeURIComponent(agentKey)}`, { method: "DELETE" }),
  connectorCatalog: () =>
    request<{ items: ConnectorCatalogItem[] }>("/api/v1/connectors/catalog"),
  listConnectors: () =>
    request<{ items: ConnectorRow[] }>("/api/v1/connectors"),
  createConnector: (body: { kind: string; display_name: string; config: Record<string, unknown>; secrets?: Record<string, unknown> }) =>
    request<ConnectorRow>("/api/v1/connectors", { method: "POST", body: JSON.stringify(body) }),
  updateConnector: (id: string, body: Record<string, unknown>) =>
    request<{ id: string }>(`/api/v1/connectors/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteConnector: (id: string) =>
    request<{ deleted: boolean }>(`/api/v1/connectors/${id}`, { method: "DELETE" }),
  verifyConnector: (id: string) =>
    request<{ ok: boolean; details: Record<string, unknown> }>(`/api/v1/connectors/${id}/verify`, { method: "POST" }),
  syncConnector: (id: string, sinceDays = 7) =>
    request<{ discovered: number; created: number; skipped_duplicates: number; errors: string[] }>(
      `/api/v1/connectors/${id}/sync?since_days=${sinceDays}`, { method: "POST" }),
  rubrics: () => request<{ items: RubricRow[] }>("/api/v1/rubrics"),
  updateActiveRubric: (body: { name: string; description?: string; spec: RubricSpec; rescore_days?: number }) =>
    request<{ id: string; version: number; rescored: number }>("/api/v1/rubrics/active", {
      method: "PUT", body: JSON.stringify(body),
    }),
  lexicon: (q?: string) =>
    request<{ items: LexiconEntryRow[] }>(`/api/v1/lexicon${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  createLexicon: (body: { term: string; aliases: string[]; category?: string | null }) =>
    request<{ id: string }>("/api/v1/lexicon", { method: "POST", body: JSON.stringify(body) }),
  deleteLexicon: (id: string) =>
    request<{ deleted: boolean }>(`/api/v1/lexicon/${id}`, { method: "DELETE" }),
  orgSettings: () =>
    request<{ org: { name: string; settings: Record<string, unknown>; retention_policy: Record<string, unknown> }; pipeline: Record<string, unknown> }>("/api/v1/settings/org"),
  audit: (params?: { action?: string }) => {
    const qs = new URLSearchParams();
    if (params?.action) qs.set("action", params.action);
    return request<{ items: AuditLogRow[] }>(`/api/v1/audit?${qs}`);
  },
  eraseSubject: (body: { phone?: string; contact_id?: string; reason: string }) =>
    request<{ erased_calls: number; erased_audio_files: number; audit_id: number }>("/api/v1/privacy/erase-subject", {
      method: "POST", body: JSON.stringify(body),
    }),
  timeseries: (days = 30) =>
    request<{ points: TimeSeriesPoint[] }>(`/api/v1/analytics/timeseries?days=${days}`),
  managers: (days = 30) =>
    request<{ items: ManagerPerformanceRow[] }>(`/api/v1/analytics/managers?days=${days}`),
  statsV2: (filters: CallFilters) => {
    const q = new URLSearchParams({ days: String(filters.days ?? 30) });
    if (filters.dateFrom) q.set("date_from", filters.dateFrom);
    if (filters.dateTo) q.set("date_to", filters.dateTo);
    return request<StatsSummaryV2>(`/api/v1/stats/summary?${q}`);
  },
};

// ── v2 management API (ТЗ §7.3) ──
export type UserRole = "admin" | "supervisor" | "analyst" | "agent" | "dpo";

export interface UserProfile {
  id: string | null;
  org_id: string;
  email: string;
  display_name: string | null;
  role: UserRole;
  team_name: string | null;
  agent_ext_ids: string[];
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  calls_count?: number;
  avg_score?: number | null;
  has_voiceprint?: boolean;
  voiceprint_samples?: number;
  is_service?: boolean;
}

export interface ConnectorCatalogField {
  name: string;
  label: string;
  type: "text" | "password" | "number" | "select";
  required: boolean;
  secret: boolean;
  placeholder?: string;
}

export interface ConnectorCatalogItem {
  kind: string;
  title: string;
  category: "crm" | "pbx";
  modes: ("pull" | "push" | "webhook")[];
  description: string;
  fields: ConnectorCatalogField[];
}

export interface ConnectorRow {
  id: string;
  kind: string;
  display_name: string | null;
  config: Record<string, unknown>;
  status: "active" | "paused" | "error";
  poll_interval_min: number;
  last_poll_at: string | null;
  last_error: string | null;
  calls_ingested_total: number;
  webhook_url: string;
  created_at: string;
}

export interface RubricRow {
  id: string;
  name: string;
  description: string | null;
  version: number;
  is_active: boolean;
  spec: RubricSpec;
  created_at: string;
}

export interface RubricRuleSpec {
  kind: "lexicon" | "predicate" | "signal" | "signal_any" | "objections" | "violations";
  lexicon?: "greeting" | "closing";
  scope?: "first_60s" | "last_60s";
  metric?: string;
  condition?: string;
  op?: ">=" | "<=" | "==" | ">" | "<";
  value?: number;
  signal?: string;
  signals?: string[];
  skip_if_missing?: boolean;
}

export interface RubricItemSpec {
  id: string;
  title: string;
  weight: number;
  rule: RubricRuleSpec;
}

export interface RubricSpec {
  rubric_id: string;
  version: number;
  max_score: number;
  items: RubricItemSpec[];
}

export interface LexiconEntryRow {
  id: string;
  term: string;
  aliases: string[];
  phonetic_key: string | null;
  category: string | null;
  case_sensitive: boolean;
  enabled: boolean;
  created_at: string;
}

export interface ManagerPerformanceRow {
  user_id: string | null;
  display_name: string;
  agent_ext: string | null;
  team_name: string | null;
  calls_total: number;
  calls_done: number;
  avg_score: number | null;
  talk_ratio_agent: number | null;
  questions_avg: number;
  objections_total: number;
  objections_handled_ratio: number | null;
  violations_count: number;
  sentiment_avg: number | null;
  criteria_scores: Record<string, { title: string; avg_pct: number }>;
}

export interface TimeSeriesPoint {
  date: string;
  calls_total: number;
  calls_done: number;
  avg_score: number | null;
  objections_count: number;
  handled_ratio: number | null;
  sentiment_avg: number | null;
}

export interface AuditLogRow {
  id: number;
  actor_id: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface StatsSummaryV2 {
  period_days: number;
  total_calls: number;
  done_calls: number;
  failed_calls: number;
  avg_score: number | null;
  avg_duration_sec: number | null;
  avg_talk_ratio_agent: number | null;
  objections_total: number;
  objections_handled_ratio: number | null;
  signals_total: number;
  violations_total: number;
  top_objections: { type: string; count: number; handled_count: number }[];
  sentiment_avg: number | null;
}
