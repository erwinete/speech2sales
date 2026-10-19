import { useCallback, useEffect, useState } from "react";
import { fmtDur, StateBadge } from "../App";
import type { CallRow } from "../api";

// «Куда позвонить в первую очередь» (doc 08 §4.1): контакты по убыванию риска.
// Клик по строке — раскрыть последние звонки контакта; клик по звонку — открыть.

interface RiskFactor {
  feature: string;
  contribution: number;
  description: string;
}

interface RiskRow {
  contact_id: string;
  score: number;
  band: string;
  top_factor: string;
  factors: RiskFactor[];
  calls_total: number | null;
  recent_call_ids: string[];
}

const BAND_COLOR: Record<string, string> = { low: "#0a7d33", medium: "#b58a00", high: "#c22" };
const BAND_RU: Record<string, string> = { low: "низкий", medium: "средний", high: "высокий" };
export default function RiskBoard({
  onOpenCall,
  onOpenContact,
}: {
  onOpenCall: (id: string) => void;
  onOpenContact: (id: string) => void;
}) {
  const [rows, setRows] = useState<RiskRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [calls, setCalls] = useState<Record<string, CallRow[]>>({});
  const [loading, setLoading] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/risks/top?limit=5", {
        headers: { "X-Api-Key": localStorage.getItem("polylog_token") ?? "dev-insecure-token" },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setRows((await res.json()).items);
      setError(null);
    } catch (e) {
      setRows([]);
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = useCallback(
    async (row: RiskRow) => {
      const cid = row.contact_id;
      if (expanded === cid) {
        setExpanded(null);
        return;
      }
      setExpanded(cid);
      if (calls[cid]) return;
      setLoading(cid);
      try {
        const res = await fetch(`/api/v1/contacts/${cid}/calls`, {
          headers: { "X-Api-Key": localStorage.getItem("polylog_token") ?? "dev-insecure-token" },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const d = await res.json();
        setCalls((prev) => ({ ...prev, [cid]: d.items }));
      } catch (e) {
        setCalls((prev) => ({ ...prev, [cid]: [] }));
        setError(`Не удалось загрузить звонки контакта: ${String(e)}`);
      } finally {
        setLoading(null);
      }
    },
    [expanded, calls],
  );

  if (error && rows !== null) {
    return (
      <section style={{ margin: "16px 0", color: "crimson" }}>
        Риск-борд недоступен: {error}
      </section>
    );
  }
  if (rows === null || rows.length === 0) return null;

  return (
    <section style={{ margin: "16px 0" }}>
      <h3 style={{ marginBottom: 0 }}>Куда позвонить в первую очередь</h3>
      <small style={{ color: "#888", display: "block", marginBottom: 6 }}>
        Контакты, ранжированные по риску потери клиента. Оценка складывается из:
        давности общения, доли пропущенных, неотработанных возражений и качества звонков.
        Клик по строке — раскрыть последние звонки контакта, клик по звонку — открыть его.
      </small>
      {rows.map((r) => {
        const color = BAND_COLOR[r.band] ?? "#888";
        const isOpen = expanded === r.contact_id;
        const list = calls[r.contact_id];
        return (
          <div key={r.contact_id} style={{ borderBottom: "1px solid #eee" }}>
            <div
              onClick={() => void toggle(r)}
              style={{ display: "flex", gap: 12, alignItems: "center", padding: "8px 12px", cursor: "pointer" }}
            >
              <strong style={{ color, minWidth: 56 }}>{r.score}</strong>
              <span style={{ fontSize: 13, color: "#666", minWidth: 66 }}>{BAND_RU[r.band] ?? r.band} риск</span>
              <span style={{ flexGrow: 1, color: "#444" }}>{r.top_factor}</span>
              <small style={{ color: "#888" }}>звонков: {r.calls_total ?? "—"} {isOpen ? "▲" : "▼"}</small>
            </div>
            {isOpen && (
              <div style={{ padding: "4px 12px 10px 68px", background: "#fafbfd" }}>
                <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>
                  Почему такой риск — вклад каждого фактора:
                </div>
                {r.factors.map((f) => (
                  <div key={f.feature} style={{ fontSize: 12, color: "#666" }}>
                    <b>{f.contribution > 0 ? `+${f.contribution}` : f.contribution}</b> — {f.description}
                  </div>
                ))}
                <div style={{ marginTop: 6 }}>
                  <div style={{ marginBottom: 6 }}>
                    <a
                      href="#"
                      onClick={(e) => {
                        e.preventDefault();
                        onOpenContact(r.contact_id);
                      }}
                      style={{ color: "#06c", fontSize: 14 }}
                    >
                      Открыть карточку клиента →
                    </a>
                  </div>
                  {loading === r.contact_id && <small>звонки загружаются…</small>}
                  {(list ?? []).map((c) => (
                    <div
                      key={c.id}
                      onClick={() => onOpenCall(c.id)}
                      style={{ display: "flex", gap: 10, padding: "4px 0", cursor: "pointer", alignItems: "center" }}
                    >
                      <small style={{ color: "#888", minWidth: 110 }}>
                        {new Date(c.started_at).toLocaleDateString("ru-RU")}
                      </small>
                      <StateBadge state={c.state} />
                      <small>{fmtDur(c.duration_sec)}</small>
                      <small style={{ color: "#06c" }}>открыть звонок →</small>
                    </div>
                  ))}
                  {list !== undefined && list.length === 0 && (
                    <small style={{ color: "#888" }}>у контакта нет звонков в базе</small>
                  )}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
