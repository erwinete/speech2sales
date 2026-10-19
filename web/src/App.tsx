import { useCallback, useEffect, useState } from "react";
import { api, type CallDetailRow, type CallFilters, type CallRow } from "./api";
import { DIRECTION_RU, OBJECTION_RU, STATE_RU, ru } from "./ru";
import CallDetail from "./components/CallDetail";
import Customer360 from "./components/Customer360";
import FilterBar from "./components/FilterBar";
import InsightsFeed from "./components/InsightsFeed";
import ObjectionClusters from "./components/ObjectionClusters";
import RiskBoard from "./components/RiskBoard";

interface Stats {
  total_calls: number;
  done_calls: number;
  avg_score: number | null;
  top_objections: { type: string; count: number }[];
}

export default function App() {
  const [filters, setFilters] = useState<CallFilters>({ days: 30 });
  const [calls, setCalls] = useState<CallRow[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<CallDetailRow | null>(null);
  const [contactsOpen, setContactsOpen] = useState(false);
  const [contactId, setContactId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (f: CallFilters) => {
    try {
      const [callsRes, statsRes] = await Promise.all([api.listCalls(f), api.stats(f)]);
      setCalls(callsRes.items);
      setStats(statsRes);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    void load(filters);
  }, [filters, load]);

  const open = useCallback(async (id: string) => {
    setSelected(id);
    setDetail(null);
    try {
      setDetail(await api.callDetail(id));
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const openContact = useCallback((id: string) => {
    setSelected(null);
    setDetail(null);
    setContactId(id);
    setContactsOpen(true);
  }, []);

  if (selected && detail) {
    return (
      <CallDetail
        detail={detail}
        onBack={() => {
          setSelected(null);
          setDetail(null);
        }}
        onOpen={(id) => void open(id)}
        onOpenContact={openContact}
      />
    );
  }

  if (contactsOpen) {
    return (
      <Customer360
        contactId={contactId}
        onSelectContact={setContactId}
        onOpenCall={(id) => void open(id)}
        onBack={() => {
          setContactsOpen(false);
          setContactId(null);
        }}
      />
    );
  }

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", maxWidth: 1100, margin: "0 auto", padding: 24 }}>
      <h1>
        Полилог{" "}
        <small style={{ color: "#888", fontSize: 14 }}>
          оперативный дашборд по всем звонкам
        </small>
      </h1>
      <div style={{ margin: "8px 0", display: "flex", gap: 8 }}>
        <span style={{ fontWeight: 600, borderBottom: "2px solid #2b6cb0", padding: "2px 4px" }}>
          Дашборд
        </span>
        <a
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setContactsOpen(true);
          }}
          style={{ color: "#06c", padding: "2px 4px" }}
        >
          Клиенты (Customer 360)
        </a>
      </div>
      <small style={{ color: "#666", display: "block", marginBottom: 8 }}>
        Все звонки отдела в одном месте: слушайте разговоры, читайте их разбор
        и следите, какие клиенты в зоне риска. Подробности по конкретному клиенту
        открываются в один клик — из блоков ниже или из списка звонков.
      </small>
      {error && <p style={{ color: "crimson" }}>{error}</p>}

      <FilterBar filters={filters} onChange={setFilters} />

      {stats && (
        <div style={{ display: "flex", gap: 16, margin: "16px 0", flexWrap: "wrap" }}>
          <Stat title={`Звонков за ${filters.days ?? 30} дн.`} value={String(stats.total_calls)} />
          <Stat title="Обработано" value={String(stats.done_calls)} />
          <Stat title="Средняя оценка звонков" value={stats.avg_score != null ? String(stats.avg_score) : "—"} />
          <Stat
            title="Топ-возражение"
            value={stats.top_objections[0]
              ? `${ru(OBJECTION_RU, stats.top_objections[0].type)} (${stats.top_objections[0].count})`
              : "—"}
          />
        </div>
      )}

      <InsightsFeed onOpenCall={(id) => void open(id)} onOpenContact={openContact} />
      <RiskBoard onOpenCall={(id) => void open(id)} onOpenContact={openContact} />
      <ObjectionClusters onOpenCall={(id) => void open(id)} />

      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 16 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "2px solid #ddd" }}>
            <th>Дата</th><th>Направление</th><th>Клиент</th><th>Длит.</th>
            <th>Статус</th><th>Цепочка</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((c) => (
            <tr
              key={c.id}
              onClick={() => void open(c.id)}
              style={{ borderBottom: "1px solid #eee", cursor: "pointer" }}
            >
              <td>{new Date(c.started_at).toLocaleString("ru-RU")}</td>
              <td>{ru(DIRECTION_RU, c.direction)}</td>
              <td>{c.phone_from ?? c.phone_to ?? "—"}</td>
              <td>
                {fmtDur(c.duration_sec)}
                {c.duration_sec != null && c.duration_sec < 15 && (
                  <span title="Короткий звонок — вне семантического анализа" style={{ color: "#9aa7b8", fontSize: 12 }}>
                    {" "}· короткий
                  </span>
                )}
              </td>
              <td><StateBadge state={c.state} /></td>
              <td>{c.chain_depth != null ? `#${(c.chain_depth ?? 0) + 1}` : "—"}</td>
            </tr>
          ))}
          {calls.length === 0 && (
            <tr><td colSpan={6} style={{ padding: 24, color: "#888" }}>
              По выбранным фильтрам звонков нет — измените период или длительность
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ title, value }: { title: string; value: string }) {
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: "10px 18px", minWidth: 140 }}>
      <div style={{ color: "#888", fontSize: 12 }}>{title}</div>
      <div style={{ fontSize: 22, fontWeight: 600 }}>{value}</div>
    </div>
  );
}

export function StateBadge({ state }: { state: string }) {
  const color =
    state === "done" ? "#0a7d33" : state === "failed" ? "#c22" : "#b58a00";
  return (
    <span style={{ background: `${color}18`, color, padding: "2px 10px", borderRadius: 12, fontSize: 13 }}>
      {ru(STATE_RU, state, state)}
    </span>
  );
}

export function fmtDur(sec: number | null): string {
  if (!sec) return "—";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
