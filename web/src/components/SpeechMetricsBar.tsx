/** Полоса речевых метрик звонка (V5-07, ТЗ v5.0 §9.1): баланс речи, темп
    (слов/мин), перебивания, самый длинный монолог, траектория тона клиента
    (начало → середина → финал), лента стадий диалога и извлечённые сущности
    (суммы, даты, контакты). */
import { Icon } from "./ui";

interface MetricsProps {
  metrics: Record<string, unknown> | null;
  mentions?: { kind: string; value: string; segment_idx: number | null }[];
}

const STAGE_RU: Record<string, string> = {
  greeting: "Приветствие",
  identification: "Знакомство",
  qualification: "Квалификация",
  presentation: "Презентация",
  objection_handling: "Возражения",
  negotiation: "Торговля",
  closing: "Закрытие",
  goodbye: "Прощание",
};

const TRAJ_ICON: Record<string, string> = {
  positive: "😊",
  neutral: "😐",
  negative: "☹",
};

const MENTION_RU: Record<string, string> = {
  amount: "Сумма",
  date: "Срок",
  email: "Email",
  phone: "Телефон",
};

export default function SpeechMetricsBar({ metrics, mentions = [] }: MetricsProps) {
  if (!metrics) return null;
  const talkRatio = (metrics["talk_ratio"] ?? {}) as Record<string, number>;
  const wpm = (metrics["wpm"] ?? {}) as Record<string, number>;
  const pauses = (metrics["pauses"] ?? {}) as { count?: number; longest_sec?: number };
  const questions = (metrics["questions"] ?? {}) as { total?: number };
  const monologue = (metrics["longest_monologue_sec"] ?? {}) as Record<string, number>;
  const trajectory = ((metrics["sentiment_trajectory"] ?? {}) as { trajectory?: string[] }).trajectory ?? [];
  const stages = ((metrics["stages"] ?? []) as { stage: string; start_ms: number; end_ms: number }[])
    .filter((s) => s.stage !== "unclassified");
  const interruptions = Number(metrics["interruptions"] ?? 0);
  const agentRatio = talkRatio["agent"];
  const clientRatio = talkRatio["client"];

  return (
    <section style={{ margin: "16px 0", padding: 16, border: "1px solid #ddd", borderRadius: 8 }}>
      <h3 style={{ margin: "0 0 8px" }}>Речь и динамика разговора</h3>
      {agentRatio != null && clientRatio != null && (
        <>
          <div style={{ fontSize: 12, color: "#666" }}>
            Баланс речи: менеджер {Math.round(agentRatio * 100)}% · клиент {Math.round(clientRatio * 100)}%
          </div>
          <div className="talk-ratio" style={{ maxWidth: 560 }}>
            <div className="agent" style={{ width: `${Math.round(agentRatio * 100)}%` }} />
            <div className="client" style={{ width: `${Math.round(clientRatio * 100)}%` }} />
          </div>
        </>
      )}
      <div className="metric-cards" style={{ maxWidth: 760, margin: "10px 0" }}>
        <div className="metric-card">
          <div className="v">{wpm["agent"] ?? "—"}</div>
          <small className="muted">слов/мин менеджер</small>
        </div>
        <div className="metric-card">
          <div className="v">{wpm["client"] ?? "—"}</div>
          <small className="muted">слов/мин клиент</small>
        </div>
        <div className="metric-card">
          <div className="v">{interruptions}</div>
          <small className="muted">перебиваний</small>
        </div>
        <div className="metric-card">
          <div className="v">{monologue["agent"] ?? "—"} с</div>
          <small className="muted">монолог менеджера</small>
        </div>
        <div className="metric-card">
          <div className="v">{monologue["client"] ?? "—"} с</div>
          <small className="muted">монолог клиента</small>
        </div>
        <div className="metric-card">
          <div className="v">{pauses["count"] ?? 0}</div>
          <small className="muted">пауз ≥ 2 с</small>
        </div>
        <div className="metric-card">
          <div className="v">{questions["total"] ?? 0}</div>
          <small className="muted">вопросов</small>
        </div>
        <div className="metric-card">
          <div className="v" style={{ fontSize: 15 }}>
            {trajectory.length
              ? trajectory.map((t, i) => <span key={i} title={t}>{TRAJ_ICON[t] ?? "😐"}</span>)
              : "—"}
          </div>
          <small className="muted">тон клиента: начало → финал</small>
        </div>
      </div>

      {stages.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 12, color: "#666", marginBottom: 4 }}>Стадии диалога</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {stages.map((s, i) => (
              <span key={i} className="badge brand" title={`${s.start_ms}–${s.end_ms} мс`}>
                {STAGE_RU[s.stage] ?? s.stage}
              </span>
            ))}
          </div>
        </div>
      )}

      {mentions.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 12, color: "#666", marginBottom: 4 }}>
            <Icon name="search" size={12} /> Извлечённые сущности
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {mentions.map((m, i) => (
              <span key={i} className="badge neutral mono" style={{ fontSize: 11 }}>
                {MENTION_RU[m.kind] ?? m.kind}: {m.value}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
