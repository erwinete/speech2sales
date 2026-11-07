/** Экран 4: Команда и коучинг (ТЗ §5.4 п.5): лидерборд + тепловая карта навыков. */
import React from "react";
import { navigate } from "../App";
import { api, type ManagerPerformanceRow } from "../api";
import { Badge, EmptyState, Skeleton } from "../components/ui";
import { scoreTone } from "../components/ui";

export default function ManagersAnalyticsPage() {
  const [items, setItems] = React.useState<ManagerPerformanceRow[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    api.managers(30).then((r) => setItems(r.items)).catch((e) => setError(String(e)));
  }, []);

  if (error) return <p style={{ color: "crimson" }}>{error}</p>;
  if (!items) return <div className="card"><Skeleton rows={6} /></div>;
  if (items.length === 0) {
    return <EmptyState icon="coach" text="В периоде 30 дней звонков менеджеров не было" />;
  }

  const leader = items.find((i) => i.avg_score != null && i.avg_score === Math.max(...items.map(x => x.avg_score ?? 0)));
  const active = items.filter(i => i.calls_total > 0);

  return (
    <div>
      <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
        <div className="kpi">
          <div className="label">Менеджеров с звонками</div>
          <div className="value">{active.length}</div>
        </div>
        <div className="kpi">
          <div className="label">Средний балл отдела</div>
          <div className="value">
            {active.length ? Math.round(active.reduce((a, i) => a + (i.avg_score ?? 0), 0) / active.length) : "—"}
          </div>
        </div>
        <div className="kpi">
          <div className="label">Лидер качества</div>
          <div className="value" style={{ fontSize: 16 }}>{leader?.display_name ?? "—"}</div>
          <div className="sub">{leader?.avg_score != null ? `${leader.avg_score} баллов` : undefined}</div>
        </div>
        <div className="kpi">
          <div className="label">Точка роста</div>
          <div className="value" style={{ fontSize: 16 }}>{items[0]?.display_name ?? "—"}</div>
          <div className="sub">самый низкий балл в отделе</div>
        </div>
      </div>

      <h3>Лидерборд за 30 дней</h3>
      <table>
        <thead>
          <tr>
            <th>Менеджер</th><th className="num">Звонков</th><th className="num">Средний балл</th>
            <th className="num">Отработка возражений</th><th className="num">Баланс речи</th>
            <th className="num">Вопросов/звонок</th><th className="num">Нарушений</th><th>Тон клиентов</th><th>ИИ-коучинг</th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => (
            <tr key={i.display_name + (i.agent_ext ?? "")} style={{ cursor: "default" }}>
              <td><b>{i.display_name}</b>{i.agent_ext && <span className="muted mono"> · {i.agent_ext}</span>}
                {i.team_name && <div className="muted" style={{ fontSize: 11 }}>{i.team_name}</div>}
              </td>
              <td className="num">{i.calls_total} <small className="muted">({i.calls_done} готово)</small></td>
              <td><Badge tone={scoreTone(i.avg_score)}>{i.avg_score ?? "—"}</Badge></td>
              <td className="num">{i.objections_handled_ratio != null ? `${Math.round(i.objections_handled_ratio * 100)}%` : "—"}</td>
              <td className="num">{i.talk_ratio_agent != null ? `${Math.round(i.talk_ratio_agent * 100)}%` : "—"}</td>
              <td className="num">{i.questions_avg}</td>
              <td className="num">{i.violations_count}</td>
              <td>{i.sentiment_avg != null ? (i.sentiment_avg > 0.2 ? "😊" : i.sentiment_avg < -0.2 ? "☹" : "😐") : "—"}</td>
              <td>
                {/* DEF-07 (ТЗ v4.0): сотрудник — на коучинг-разбор в ИИ-Анализатор */}
                <button onClick={() => navigate(`/ai-lab?mode=rubert_scores&agent_name=${encodeURIComponent(i.display_name)}&days=30`)}>
                  ✨ Разобрать в ИИ
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <small className="section-hint">
        Матрица навыков по критериям рубрики появится после накопления скоринга по кастомным критериям (сейчас — средний балл).
      </small>
    </div>
  );
}
