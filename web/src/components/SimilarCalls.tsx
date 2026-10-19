import { useEffect, useState } from "react";
import { api, type CallDetailRow } from "../api";
import { fmtDur } from "../App";

// Похожие звонки (M9): kNN по эмбеддинг-вектору; клик открывает звонок.
// 409 (нет вектора) / 501 (sqlite) — блок просто не показывается.

interface SimilarItem {
  call_id: string;
  similarity: number;
  phone: string | null;
  started_at: string;
  duration_sec: number | null;
}

export default function SimilarCalls({
  call,
  onOpen,
}: {
  call: CallDetailRow;
  onOpen: (id: string) => void;
}) {
  const [items, setItems] = useState<SimilarItem[] | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .similar(call.id)
      .then((r) => {
        if (alive) setItems(r.items);
      })
      .catch(() => {
        if (alive) setItems([]); // тихо: нет вектора/поиск недоступен
      });
    return () => {
      alive = false;
    };
  }, [call.id]);

  if (items === null || items.length === 0) return null;

  return (
    <section style={{ margin: "16px 0" }}>
      <h3>Похожие звонки</h3>
      {items.map((s) => (
        <div
          key={s.call_id}
          onClick={() => onOpen(s.call_id)}
          style={{
            display: "flex",
            gap: 12,
            alignItems: "center",
            padding: "8px 12px",
            borderBottom: "1px solid #eee",
            cursor: "pointer",
          }}
        >
          <span
            style={{
              fontWeight: 600,
              color: s.similarity >= 0.995 ? "#c22" : "#0a58ca",
              minWidth: 56,
            }}
          >
            {Math.round(s.similarity * 100)}%
          </span>
          <span>{s.phone ?? "—"}</span>
          <span style={{ color: "#888", fontSize: 13 }}>
            {new Date(s.started_at).toLocaleDateString("ru-RU")} · {fmtDur(s.duration_sec)}
          </span>
          {s.similarity >= 0.995 && (
            <small style={{ color: "#c22" }}>возможно, дубль записи</small>
          )}
        </div>
      ))}
    </section>
  );
}
