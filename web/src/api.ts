const TOKEN = () => localStorage.getItem("polylog_token") ?? "dev-insecure-token";

export interface CallFilters {
  days?: number;
  dateFrom?: string;
  dateTo?: string;
  durationMin?: number | null;
  durationMax?: number | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // R-01 (ТЗ v3.0 §8.1): для FormData Content-Type не выставляется — браузер
  // сам формирует multipart/form-data с boundary, иначе FastAPI вернёт 422.
  const isFormData = init?.body instanceof FormData;
  const res = await fetch(path, {
    ...init,
    headers: {
      "X-Api-Key": TOKEN(),
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
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
  text_mentions?: { kind: string; value: string; segment_idx: number | null }[];
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
  // R-01/UI-01: FormData — request() сам не ставит Content-Type
  uploadCall: (form: FormData) =>
    request<{ call: CallRow; created: boolean; message: string }>("/api/v1/calls/upload", {
      method: "POST",
      body: form,
    }),
  // R-08: роль сегмента — формой (совместимо с бэкендом)
  setSegmentRole: (callId: string, idx: number, speaker: "agent" | "client") =>
    request<{ call_id: string; idx: number; speaker: string }>(
      `/api/v1/calls/${callId}/segments/${idx}/role`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ speaker }),
      }),
  contactRisk: (contactId: string) =>
    request<RiskInfo>(`/api/v1/contacts/${contactId}/risk`),
  insightsNew: () =>
    request<{ items: {
      id: string;
      kind: string;
      severity: string;
      contact_id: string | null;
      payload: { score?: number; band?: string; factors?: { feature: string; contribution: number; description: string }[]; contact_id?: string };
      generated_by: string;
      created_at: string;
    }[] }>("/api/v1/insights?status=new"),
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
  // бинарный ответ (waveform) — fetch допустим только внутри api.ts (UI-01)
  audioWaveform: (url: string): Promise<ArrayBuffer> =>
    fetch(url).then((r) => {
      if (!r.ok) throw new Error(`API ${r.status}`);
      return r.arrayBuffer();
    }),
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

  // ── AI Lab (ТЗ v3.0 §4.4) ──
  aiPresets: () =>
    request<AiPresets>("/api/v1/ai/presets"),
  previewContext: (body: AiContextRequest) =>
    request<PreviewContextResponse>("/api/v1/ai/preview-context", {
      method: "POST", body: JSON.stringify(body),
    }),
  aiAnalyze: (body: AiAnalyzeRequest) =>
    request<AiAnalyzeResponse>("/api/v1/ai/analyze", {
      method: "POST", body: JSON.stringify(body),
    }),
  // DEF-03 (ТЗ v4.0): SSE-стриминг анализа; fetch — единственный в api.ts
  aiAnalyzeStream: async (body: AiAnalyzeRequest, onEvent: (e: AiStreamEvent) => void): Promise<void> => {
    const res = await fetch("/api/v1/ai/analyze/stream", {
      method: "POST",
      headers: { "X-Api-Key": TOKEN(), "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok || !res.body) {
      const t2 = await res.text();
      throw new Error(`API ${res.status}: ${t2.slice(0, 200)}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const blocks = buf.split("\n\n");
      buf = blocks.pop() ?? "";
      for (const block of blocks) {
        let evt = "message";
        const dataLines: string[] = [];
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) evt = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (!dataLines.length) continue;
        let data: Record<string, unknown> = {};
        try { data = JSON.parse(dataLines.join("\n")); } catch { data = { raw: dataLines.join("\n") }; }
        onEvent({ type: evt as AiStreamEvent["type"], data });
      }
    }
  },
  aiModels: (baseUrl: string, apiKey?: string) => {
    const q = new URLSearchParams({ base_url: baseUrl });
    if (apiKey) q.set("api_key", apiKey);
    return request<{ items: { id: string; name: string | null; context_length: number | null }[] }>(
      `/api/v1/ai/models?${q}`);
  },
  aiRuns: () =>
    request<{ items: AiRunRow[] }>("/api/v1/ai/runs"),
  aiRun: (id: string) =>
    request<AiRunDetail>(`/api/v1/ai/runs/${id}`),
  mcpConfig: (sanitizePii = true) =>
    request<McpConfig>(`/api/v1/ai/mcp-config?sanitize_pii=${sanitizePii}`),
  mcpRpc: (payload: Record<string, unknown>) =>
    request<Record<string, unknown>>("/api/v1/mcp/rpc", {
      method: "POST", body: JSON.stringify(payload),
    }),
  // V5-03: сценарий тренажёра (Слой B)
  scenarioFromCall: (id: string) =>
    request<TrainerScenario>(`/api/v1/calls/${id}/scenario`),
  scenarioFromCluster: (body: { days?: number; limit?: number; objection_type?: string | null }) =>
    request<TrainerScenario>("/api/v1/exports/scenario-from-cluster", {
      method: "POST", body: JSON.stringify(body),
    }),
  exportsHistory: () =>
    request<{ items: ExportJobRow[] }>("/api/v1/exports"),
  // V5-05: выгрузка результата в CRM
  pushCrm: (id: string, body: { webhook_url?: string } = {}) =>
    request<{ sent: number; targets: string[]; errors: string[]; note: string }>(
      `/api/v1/calls/${id}/push-crm`, { method: "POST", body: JSON.stringify(body) }),
  // V5-02: воронка стадий диалога
  stagesFunnel: (days = 30) =>
    request<StagesFunnel>(`/api/v1/analytics/stages-funnel?days=${days}`),
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

// ── AI Lab: типы (ТЗ v3.0 §4.4) ──

export interface PiiSanitizerConfig {
  enabled: boolean;
  strip_names: boolean;
  strip_phones_emails: boolean;
  strip_orders_contracts: boolean;
  strip_internal_ids: boolean;
  strip_company_names: boolean;
  custom_stop_words: string[];
}

export interface PiiStats {
  total_redactions: number;
  by_category: Record<string, number>;
  alias_map: Record<string, string>;
}

export interface AiContextRequest {
  mode: "rubert_scores" | "problematic_calls" | "transcripts_range";
  date_from?: string | null;
  date_to?: string | null;
  days?: number;
  agent_user_id?: string | null;
  risk_band?: string | null;
  score_max?: number | null;
  direction?: string | null;
  min_duration_sec?: number | null;
  objection_type?: string | null;
  call_ids?: string[];
  limit_calls?: number;
  pii: PiiSanitizerConfig;
}

export interface AiAnalyzeRequest extends AiContextRequest {
  provider: string;
  base_url: string;
  api_key?: string | null;
  model: string;
  system_prompt: string;
  user_prompt: string;
  temperature?: number;
  max_tokens?: number;
}

export interface AiPreset {
  id: string;
  title: string;
  mode: string;
  system_prompt: string;
  user_prompt: string;
}

export interface AiPresets {
  presets: AiPreset[];
  recommended_models: { id: string; label: string }[];
  system_prompt_default: string;
  provider_settings: {
    base_url: string;
    api_key_masked: string | null;
    model: string | null;
  };
}

export interface PreviewContextResponse {
  mode: string;
  calls_matched: number;
  estimated_tokens: number;
  pii_stats: PiiStats;
  context_preview: string;
  structured_bundle: Record<string, unknown>;
}

export interface AiAnalyzeResponse {
  run_id: string;
  result_markdown: string;
  pii_stats: PiiStats;
  alias_map: Record<string, string>;
  token_usage: Record<string, number>;
  calls_count: number;
}

export interface AiRunRow {
  id: string;
  mode: string;
  provider: string;
  model_id: string;
  calls_count: number;
  status: string;
  error_message: string | null;
  prompt_text: string;
  created_at: string;
}

export interface AiRunDetail extends AiRunRow {
  filter_spec: Record<string, unknown>;
  pii_config: Record<string, unknown>;
  prompt_text: string;
  call_ids: string[];
  result_markdown: string | null;
  token_usage: Record<string, number> | null;
}

export interface McpConfig {
  tools: { name: string; description: string }[];
  starter_prompt: string;
  harnesses: Record<
    string,
    {
      title: string;
      cli_command?: string;
      mcp_json?: Record<string, unknown>;
      config_toml?: string;
      config_json?: Record<string, unknown>;
    }
  >;
}


// ── AI Lab: SSE-стриминг (DEF-03) ──

export interface AiStreamEvent {
  type: "meta" | "reasoning" | "content" | "done" | "error";
  data: Record<string, unknown>;
}


// ── ТЗ v5.0 (V5-02/03/05/06) ──

export interface AiAnalyzeStreamRequest extends AiAnalyzeRequest {
  map_reduce?: boolean;
}

export interface TrainerScenario {
  schema_version: string;
  scenario_id: string;
  spec: string;
  title: string;
  description?: string | null;
  persona: Record<string, unknown>;
  objections: {
    id: string;
    trigger_phrases: string[];
    ideal_responses: { text: string; why?: string | null }[];
    bad_responses?: { text: string; why?: string | null }[];
    difficulty?: number;
  }[];
  success_criteria: { id: string; description: string; weight: number }[];
  metadata: Record<string, unknown>;
}

export interface ExportJobRow {
  id: string;
  kind: string;
  filter_spec: Record<string, unknown>;
  status: string;
  file_key: string | null;
  created_at: string;
}

export interface StagesFunnel {
  days: number;
  calls_analyzed: number;
  calls_with_stages: number;
  avg_depth: number;
  items: { stage: string; stage_ru: string; calls_reached: number; conversion: number }[];
}
