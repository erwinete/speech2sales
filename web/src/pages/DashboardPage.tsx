/** Экран 1: Оперативный дашборд РОПа (ТЗ §5.4 п.2): KPI, графики Recharts,
    вкладки инсайтов, реестр звонков с пагинацией и фильтрами. */
import React from "react";
import {
  Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, type CallFilters, type CallRow, type StagesFunnel, type StatsSummaryV2 } from "../api";
import { ru, OBJECTION_RU } from "../ru";
import { Badge, EmptyState, Skeleton, Tabs, scoreTone } from "../components/ui";
import { fmtDur, StateBadge } from "../App";
import InsightsFeed from "../components/InsightsFeed";
import RiskBoard from "../components/RiskBoard";
import ObjectionClusters from "../components/ObjectionClusters";
import FilterBar from "../components/FilterBar";

interface Props {
  route: { path: string; query: URLSearchParams };
  onCallsLoaded: (n: number) => void;
  onOpenCall: (id: string) => void;
  onOpenContacts: () => void;
}

const PAGE_SIZE = 25;

export default function DashboardPage({ route, onCallsLoaded, onOpenCall, onOpenContacts }: Props) {
  const [filters, setFilters] = React.useState<CallFilters>({ days: 30 });
  const [calls, setCalls] = React.useState<CallRow[] | null>(null);
  const [total, setTotal] = React.useState(0);
  const [page, setPage] = React.useState(0);
  const [stats, setStats] = React.useState<StatsSummaryV2 | null>(null);
  const [points, setPoints] = React.useState<{ date: string; calls_total: number; avg_score: number | null }[] | null>(null);
  const [funnel, setFunnel] = React.useState<StagesFunnel | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [tab, setTab] = React.useState("insights");

  React.useEffect(() => {
    const q = route.query.get("q");
    if (q) setFilters((f) => ({ ...f }));
  }, [route]);

  const load = React.useCallback(async (f: CallFilters, _p: number) => {
    try {
      const [callsRes, statsRes, tsRes, funnelRes] = await Promise.all([
        api.listCalls(f),
        api.statsV2(f),
        api.timeseries(f.days ?? 30),
        api.stagesFunnel(f.days ?? 30).catch(() => null),
      ]);
      setCalls(callsRes.items);
      setTotal(callsRes.total);
      setStats(statsRes);
      setPoints(tsRes.points);
      if (funnelRes) setFunnel(funnelRes);
      setError(null);
      onCallsLoaded(statsRes.done_calls);
    } catch (e) {
      setError(String(e));
    }
  }, [onCallsLoaded]);

  React.useEffect(() => {
    void load(filters, page);
  }, [filters, page, load]);

  const changeFilters = (f: CallFilters) => { setFilters(f); setPage(0); };

  const handled = stats?.objections_total
    ? Math.round((stats.objections_total * (stats.objections_handled_ratio ?? 0)) )
    : null;
  const talkAgent = stats?.avg_talk_ratio_agent != null ? Math.round(stats.avg_talk_ratio_agent * 100) : null;

  return (
    <div>
      <FilterBar filters={filters} onChange={changeFilters} />
      {error && <p style={{ color: "crimson" }}>{error}</p>}

      {!stats ? (
        <div className="card"><Skeleton rows={4} /></div>
      ) : (
        <div className="kpi-grid">
          <Kpi label="Звонков" value={String(stats.total_calls)}
            sub={`обработано ${stats.done_calls} · ошибок ${stats.failed_calls}`} />
          <Kpi label="Средняя оценка" value={stats.avg_score != null ? String(stats.avg_score) : "—"}
            progress={stats.avg_score} />
          <Kpi label="Отработка возражений"
            value={stats.objections_handled_ratio != null ? `${Math.round(stats.objections_handled_ratio * 100)}%` : "—"}
            sub={`из ${stats.objections_total}`} progress={handled ?? 0} max={Math.max(stats.objections_total, 1)} />
          <Kpi label="Баланс речи (менеджер)"
            value={talkAgent != null ? `${talkAgent}%` : "—"}
            sub={talkAgent != null && talkAgent >= 40 && talkAgent <= 55 ? "в коридоре 40–55%" : "вне коридора 40–55%"} />
          <Kpi label="Сигналы / нарушения"
            value={`${stats.signals_total} / ${stats.violations_total}`}
            sub="интерес клиента vs ошибки скрипта" />
          <Kpi label="Главный барьер"
            value={stats.top_objections[0] ? ru(OBJECTION_RU, stats.top_objections[0].type) : "—"}
            sub={stats.top_objections[0] ? `${stats.top_objections[0].count} раз` : undefined} />
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: 12 }}>
        <div className="card">
          <div className="card-title"><h3>Динамика звонков и оценки</h3></div>
          {!points ? <Skeleton /> : (
            <ComposedChart width={560} height={220} data={points.map(p => ({ ...p, date: p.date.slice(5) }))}>
              <CartesianGrid stroke="var(--border-subtle)" />
              <XAxis dataKey="date" fontSize={11} />
              <YAxis fontSize={11} />
              <Tooltip />
              <Bar dataKey="calls_total" name="Звонков" fill="var(--brand-primary)" radius={[3, 3, 0, 0]} />
              <Line dataKey="avg_score" name="Средний балл" stroke="var(--status-success)" dot={false} />
            </ComposedChart>
          )}
        </div>
        <div className="card">
          <div className="card-title"><h3>Топ-возражения</h3></div>
          {!stats ? <Skeleton /> : stats.top_objections.length === 0 ? (
            <EmptyState icon="alert" text="Возражений в периоде нет" />
          ) : (
            <BarChart width={360} height={220} data={stats.top_objections.map(o => ({
              name: ru(OBJECTION_RU, o.type), handled: o.handled_count,
              unhandled: o.count - o.handled_count,
            }))} layout="vertical">
              <XAxis type="number" hide />
              <YAxis dataKey="name" type="category" width={110} fontSize={11} />
              <Tooltip />
              <Legend />
              <Bar dataKey="handled" name="Отработано" stackId="a" fill="var(--status-success)" />
              <Bar dataKey="unhandled" name="Не отработано" stackId="a" fill="var(--status-warning)" />
            </BarChart>
          )}
        </div>
      </div>

      {/* V5-07 (ТЗ v5.0): воронка стадий диалога — где обрывается скрипт */}
      {funnel && funnel.calls_with_stages > 0 && (
        <div className="card">
          <div className="card-title">
            <h3>Воронка стадий диалога</h3>
            <small className="muted">
              звонков со стадиями: {funnel.calls_with_stages} · средняя глубина {funnel.avg_depth}
            </small>
          </div>
          <BarChart
            width={860} height={200}
            data={funnel.items.map((i) => ({ name: i.stage_ru, reached: i.calls_reached }))}
          >
            <CartesianGrid stroke="var(--border-subtle)" />
            <XAxis dataKey="name" fontSize={11} />
            <YAxis fontSize={11} allowDecimals={false} />
            <Tooltip />
            <Bar dataKey="reached" name="Звонков достигло" fill="var(--brand-primary)" radius={[3, 3, 0, 0]} />
          </BarChart>
        </div>
      )}

      <Tabs
        tabs={[
          { key: "insights", label: "Что требует внимания" },
          { key: "risks", label: "Приоритет прозвона" },
          { key: "clusters", label: "Кластеры формулировок" },
        ]}
        active={tab}
        onChange={setTab}
      />
      {tab === "insights" && <InsightsFeed onOpenCall={onOpenCall} onOpenContact={onOpenContacts} />}
      {tab === "risks" && <RiskBoard onOpenCall={onOpenCall} onOpenContact={onOpenContacts} />}
      {tab === "clusters" && <ObjectionClusters onOpenCall={onOpenCall} />}

      <h3 style={{ marginTop: 20 }}>Реестр звонков</h3>
      {!calls ? (
        <Skeleton rows={6} />
      ) : calls.length === 0 ? (
        <EmptyState icon="phone" text="По выбранным фильтрам звонков нет — измените период или длительность" />
      ) : (
        <table>
          <thead>
            <tr>
              <th>Дата и время</th><th>Направление</th><th>Клиент</th>
              <th>Длит.</th><th>Оценка</th><th>Цепочка</th><th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {calls.map((c) => (
              <tr key={c.id} onClick={() => onOpenCall(c.id)}>
                <td className="mono">{new Date(c.started_at).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" })}</td>
                <td>{ru({ inbound: "входящий", outbound: "исходящий", internal: "внутренний" }, c.direction)}</td>
                <td className="mono">{c.phone_from ?? c.phone_to ?? "—"}</td>
                <td className="mono">{fmtDur(c.duration_sec)}</td>
                <td><Badge tone={scoreTone(null)}>—</Badge></td>
                <td className="mono">{c.chain_depth != null ? `#${(c.chain_depth ?? 0) + 1}` : "—"}</td>
                <td><StateBadge state={c.state} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="pagination">
        <span>Показано {Math.min(page * PAGE_SIZE + 1, total)}–{Math.min((page + 1) * PAGE_SIZE, total)} из {total}</span>
        <button disabled={page === 0} onClick={() => setPage(page - 1)}>Назад</button>
        <button disabled={(page + 1) * PAGE_SIZE >= total} onClick={() => setPage(page + 1)}>Вперёд</button>
      </div>
    </div>
  );
}

function Kpi({ label, value, sub, progress, max = 100 }: { label: string; value: string; sub?: string; progress?: number | null; max?: number }) {
  return (
    <div className="kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
      {progress != null && (
        <div className="progress"><div style={{ width: `${Math.min(100, Math.round((progress / max) * 100))}%` }} /></div>
      )}
    </div>
  );
}
