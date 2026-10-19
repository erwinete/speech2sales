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

export interface CallDetailRow extends CallRow {
  segments: Segment[];
  metrics: Record<string, unknown> | null;
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
};
