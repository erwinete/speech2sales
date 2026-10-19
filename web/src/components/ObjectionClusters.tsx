import { useEffect, useState } from "react";

import { OBJECTION_RU } from "../ru";

// «О чём чаще всего спорят» (doc 02 §5 objection_pattern): кластеры похожих
// формулировок; клик — раскрыть звонки, где прозвучало.

interface Cluster {
  size: number;
  quotes: string[];
  top_types: [string, number][];
  dominant_type: string | null;
  calls: { call_id: string; phone?: string | null; started_at?: string | null }[];
}

export default function ObjectionClusters({ onOpenCall }: { onOpenCall: (id: string) => void }) {
  const [clusters, setClusters] = useState<Cluster[] | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/v1/insights/objection-clusters?days=90", {
      headers: { "X-Api-Key": localStorage.getItem("polylog_token") ?? "dev-insecure-token" },
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        if (alive) setClusters(d.clusters);
      })
      .catch(() => {
        if (alive) setClusters([]);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (clusters === null || clusters.length === 0) return null;

  return (
    <section style={{ margin: "16px 0" }}>
      <h3 style={{ marginBottom: 0 }}>О чём чаще всего спорят</h3>
      <small style={{ color: "#888", display: "block", marginBottom: 6 }}>
        Похожие формулировки возражений сгруппированы. Клик — раскрыть звонки,
        где прозвучало; клик по звонку — открыть транскрипт.
      </small>
      {clusters.slice(0, 6).map((c, i) => {
        const dom = c.top_types[0]?.[0] ?? c.dominant_type ?? "other";
        const isOpen = expanded === i;
        return (
          <div key={i} style={{ borderBottom: "1px solid #eee" }}>
            <div
              onClick={() => setExpanded(isOpen ? null : i)}
              style={{ display: "flex", gap: 12, alignItems: "center", padding: "8px 12px", cursor: "pointer" }}
            >
              <strong style={{ minWidth: 40 }}>{c.size} шт.</strong>
              <span style={{ flexGrow: 1 }}>
                {OBJECTION_RU[dom] ?? dom}
                {c.quotes[0] && (
                  <small style={{ color: "#888" }}> — «{c.quotes[0].slice(0, 80)}»</small>
                )}
              </span>
              <small>{isOpen ? "▲" : "▼"}</small>
            </div>
            {isOpen && (
              <div style={{ padding: "4px 12px 10px 40px", background: "#fafbfd" }}>
                {c.calls.map((cc) => (
                  <div
                    key={cc.call_id}
                    onClick={() => onOpenCall(cc.call_id)}
                    style={{ padding: "4px 0", cursor: "pointer", color: "#06c", fontSize: 13 }}
                  >
                    {cc.phone ?? "—"}
                    {cc.started_at
                      ? ` · ${new Date(cc.started_at).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" })}`
                      : ""}{" "}
                    — открыть звонок →
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
