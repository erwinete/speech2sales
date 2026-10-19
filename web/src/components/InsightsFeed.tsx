import { useCallback, useEffect, useState } from "react";
import { StateBadge } from "../App";
import { OBJECTION_RU, RESPONSE_RU, ru } from "../ru";

// «Что требует внимания» (doc 08 §4.2): лента инсайтов — риск-карточки
// (risk_account) и повторяющиеся нерешённые проблемы (repeat_objection,
// Root-Cause). Фильтр по severity; кнопки Учтено/Не показывать; дрилдауны.

interface InsightItem {
  id: string;
  kind: string;
  severity: string;
  contact_id: string | null;
  payload: {
    score?: number;
    band?: string;
    factors?: { feature: string; contribution: number; description: string }[];
    contact_id?: string;
    type?: string;
    calls?: number;
    last_status?: string | null;
    last_at?: string;
  };
  generated_by: string;
  created_at: string;
}

interface CallRow {
  id: string;
  started_at: string;
  state: string;
  duration_sec: number | null;
}

const BAND_RU: Record<string, string> = { low: "низкий", medium: "средний", high: "высокий" };
const BAND_COLOR: Record<string, string> = { low: "#0a7d33", medium: "#b58a00", high: "#c22" };
const SEVERITY_RU: Record<string, string> = { critical: "критичное", warning: "предупреждение", info: "инфо" };
const FEATURE_RU: Record<string, string> = {
  days_silence: "Молчание (дней с последнего звонка)",
  unanswered_ratio: "Пропущенные",
  unhandled_ratio: "Неотработанные возражения",
  avg_score: "Качество звонков",
};

type SeverityFilter = "all" | "critical" | "warning";

export default function InsightsFeed({
  onOpenCall,
  onOpenContact,
}: {
  onOpenCall: (id: string) => void;
  onOpenContact: (id: string) => void;
}) {
  const [items, setItems] = useState<InsightItem[] | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [calls, setCalls] = useState<Record<string, CallRow[]>>({});
  const [severity, setSeverity] = useState<SeverityFilter>("all");

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/insights?status=new", {
        headers: { "X-Api-Key": localStorage.getItem("polylog_token") ?? "dev-insecure-token" },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setItems((await res.json()).items);
    } catch {
      setItems([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (id: string, action: "ack" | "dismiss") => {
    await fetch(`/api/v1/insights/${id}/${action}`, { method: "POST" });
    setItems((prev) => (prev ? prev.filter((i) => i.id !== id) : prev));
  };

  const toggleCalls = useCallback(
    async (contactId: string) => {
      if (expanded === contactId) {
        setExpanded(null);
        return;
      }
      setExpanded(contactId);
      if (calls[contactId]) return;
      const res = await fetch(`/api/v1/contacts/${contactId}/calls`, {
        headers: { "X-Api-Key": localStorage.getItem("polylog_token") ?? "dev-insecure-token" },
      });
      if (res.ok) {
        const d = await res.json();
        setCalls((prev) => ({ ...prev, [contactId]: d.items }));
      }
    },
    [expanded, calls],
  );

  if (items === null || items.length === 0) return null;

  const visible = items.filter((i) => severity === "all" || i.severity === severity);

  return (
    <section style={{ margin: "16px 0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap" }}>
        <h3 style={{ marginBottom: 0 }}>Что требует внимания</h3>
        <div style={{ display: "flex", gap: 6 }}>
          {(["all", "critical", "warning"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSeverity(s)}
              style={severity === s ? { fontWeight: 600, borderColor: "#2b6cb0", color: "#2b6cb0" } : undefined}
            >
              {s === "all" ? "Все" : SEVERITY_RU[s]}
            </button>
          ))}
        </div>
      </div>
      <small style={{ color: "#888", display: "block", marginBottom: 6 }}>
        Риски потери клиента и повторяющиеся нерешённые проблемы (клиент ходит по кругу).
        Числа у факторов — вклад в риск. Кнопки: «Учтено» — вы уже сработали,
        «Не показывать» — убрать из ленты. Клик «звонки» — раскрыть историю контакта.
      </small>
      {visible.length === 0 && (
        <p style={{ color: "#888" }}>Под этот фильтр инсайтов нет</p>
      )}
      {visible.map((i) => {
        if (i.kind === "repeat_objection") {
          return (
            <div
              key={i.id}
              style={{
                border: "1px solid #b58a0055",
                background: "#b58a000d",
                borderRadius: 8,
                padding: "10px 14px",
                margin: "8px 0",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <strong style={{ color: "#b58a00" }}>
                  Повторяющаяся проблема: {ru(OBJECTION_RU, i.payload.type, i.payload.type)}
                </strong>
                <small style={{ color: "#888" }}>{new Date(i.created_at).toLocaleDateString("ru-RU")}</small>
              </div>
              <div style={{ fontSize: 13, color: "#444" }}>
                {i.payload.calls ?? "—"} звонков без успеха; последний раз —{" "}
                {ru(RESPONSE_RU, i.payload.last_status, "не отработано")}
                {i.payload.last_at && ` (${new Date(i.payload.last_at).toLocaleDateString("ru-RU")})`}
              </div>
              <div style={{ marginTop: 6, display: "flex", gap: 8 }}>
                {i.contact_id && <button onClick={() => onOpenContact(i.contact_id as string)}>Карточка клиента</button>}
                <button onClick={() => void act(i.id, "ack")}>Учтено</button>
                <button onClick={() => void act(i.id, "dismiss")} style={{ color: "#888" }}>
                  Не показывать
                </button>
              </div>
            </div>
          );
        }

        const color = BAND_COLOR[i.payload.band ?? "medium"] ?? "#b58a00";
        const cid = i.contact_id ?? i.payload.contact_id ?? "";
        const isOpen = expanded === cid && cid !== "";
        return (
          <div
            key={i.id}
            style={{
              border: `1px solid ${color}55`,
              background: `${color}0d`,
              borderRadius: 8,
              padding: "10px 14px",
              margin: "8px 0",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <strong style={{ color }}>
                Риск потери клиента: {i.payload.score ?? "—"} / 100 —{" "}
                {BAND_RU[i.payload.band ?? ""] ?? i.payload.band}
              </strong>
              <small style={{ color: "#888" }}>{new Date(i.created_at).toLocaleDateString("ru-RU")}</small>
            </div>
            {(i.payload.factors ?? []).slice(0, 3).map((f) => (
              <div key={f.feature} style={{ fontSize: 13, color: "#444" }}>
                <b style={{ color: f.contribution > 0 ? "#c22" : "#0a7d33" }}>
                  {f.contribution > 0 ? `+${f.contribution}` : f.contribution}
                </b>{" "}
                <b>{FEATURE_RU[f.feature] ?? f.feature}:</b> {f.description}
              </div>
            ))}
            <div style={{ marginTop: 6, display: "flex", gap: 8 }}>
              {cid && (
                <button onClick={() => void toggleCalls(cid)}>
                  {isOpen ? "Скрыть звонки" : "Показать звонки"}
                </button>
              )}
              {cid && <button onClick={() => onOpenContact(cid)}>Карточка клиента</button>}
              <button onClick={() => void act(i.id, "ack")}>Учтено</button>
              <button onClick={() => void act(i.id, "dismiss")} style={{ color: "#888" }}>
                Не показывать
              </button>
            </div>
            {isOpen && cid && (
              <div style={{ marginTop: 6, background: "#fff", borderRadius: 6, padding: "4px 10px" }}>
                {(calls[cid] ?? []).map((c) => (
                  <div
                    key={c.id}
                    onClick={() => onOpenCall(c.id)}
                    style={{ display: "flex", gap: 10, padding: "4px 0", cursor: "pointer", alignItems: "center" }}
                  >
                    <small style={{ color: "#888", minWidth: 110 }}>
                      {new Date(c.started_at).toLocaleDateString("ru-RU")}
                    </small>
                    <StateBadge state={c.state} />
                    <small style={{ color: "#06c" }}>открыть звонок →</small>
                  </div>
                ))}
                {(calls[cid] ?? []).length === 0 && (
                  <small style={{ color: "#888" }}>у контакта нет звонков в базе</small>
                )}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
