import { useCallback, useEffect, useState } from "react";
import { fmtDur, StateBadge } from "../App";
import { api, type CardCall, type ContactCard, type ContactHit } from "../api";
import { DIRECTION_RU, OBJECTION_RU, RESPONSE_RU, ru } from "../ru";

// Customer 360 (doc 03 §4, doc 08 §4.4): поиск клиента по номеру/имени →
// карточка: профиль, статистика, риск, таймлайн общения, граф связей,
// похожие звонки. Данные — /contacts/search + /contacts/{id}/card.

const KIND_RU: Record<string, string> = {
  email: "Письмо",
  chat: "Чат",
  meeting: "Встреча",
  sms: "СМС",
  call: "Звонок",
};

const BAND_COLOR: Record<string, string> = { low: "#0a7d33", medium: "#b58a00", high: "#c22" };
const BAND_RU: Record<string, string> = { low: "низкий", medium: "средний", high: "высокий" };
const FEATURE_RU: Record<string, string> = {
  days_silence: "Молчание",
  unanswered_ratio: "Пропущенные",
  unhandled_ratio: "Неотработанные возражения",
  avg_score: "Качество звонков",
};

const scoreColor = (score: number | null | undefined): string =>
  score == null ? "#888" : score < 40 ? "#c22" : score < 65 ? "#b58a00" : "#0a7d33";

// Сентимент клиента −1…+1 → глиф и цвет (DoD М2)
const sentimentEmoji = (score: number | null | undefined): string =>
  score == null ? "" : score > 0.2 ? "😊" : score < -0.2 ? "☹" : "😐";
const trendLabel = (trend: number | null | undefined): string => {
  if (trend == null) return "";
  if (trend > 0.1) return `↑ +${trend.toFixed(2)}`;
  if (trend < -0.1) return `↓ ${trend.toFixed(2)}`;
  return "→ стабильно";
};

const fmtDate = (iso: string | null): string =>
  iso ? new Date(iso).toLocaleDateString("ru-RU") : "—";

const fmtTalk = (sec: number): string => {
  if (sec < 60) return `${sec} c`;
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h > 0 ? `${h} ч ${m} мин` : `${m} мин`;
};

export default function Customer360({
  contactId,
  onSelectContact,
  onOpenCall,
  onBack,
}: {
  contactId: string | null;
  onSelectContact: (id: string | null) => void;
  onOpenCall: (id: string) => void;
  onBack: () => void;
}) {
  return contactId === null ? (
    <ContactSearch onPick={onSelectContact} onBack={onBack} />
  ) : (
    <ContactCardView contactId={contactId} onSelectContact={onSelectContact} onOpenCall={onOpenCall} />
  );
}

function ContactSearch({
  onPick,
  onBack,
}: {
  onPick: (id: string) => void;
  onBack: () => void;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "high" | "risk" | "unhandled">("all");
  const [hits, setHits] = useState<ContactHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const searchMode = query.trim().length >= 2;

  useEffect(() => {
    const q = query.trim();
    // пустой запрос — общий реестр всех клиентов, от 2 символов — поиск
    const t = setTimeout(() => {
      api
        .searchContacts(searchMode ? q : null)
        .then((r) => {
          setHits(r.items);
          setError(null);
        })
        .catch((e) => setError(String(e)));
    }, searchMode ? 300 : 0);
    return () => clearTimeout(t);
  }, [query, searchMode]);

  const visible = (hits ?? []).filter((h) => {
    if (filter === "high") return h.risk_band === "high";
    if (filter === "risk") return h.risk_band === "high" || h.risk_band === "medium";
    if (filter === "unhandled") return h.objections_unhandled > 0;
    return true;
  });

  const FILTERS: { key: typeof filter; label: string }[] = [
    { key: "all", label: "Все" },
    { key: "high", label: "Высокий риск" },
    { key: "risk", label: "Риск: средний и выше" },
    { key: "unhandled", label: "Есть неотработанные возражения" },
  ];

  return (
    <div>
      <a
        href="#"
        onClick={(e) => {
          e.preventDefault();
          onBack();
        }}
        style={{ color: "#06c", fontSize: 14 }}
      >
        ← На дашборд
      </a>
      <h2 style={{ marginBottom: 4 }}>Клиенты</h2>
      <small style={{ color: "#666", display: "block", marginBottom: 12 }}>
        {searchMode
          ? "Результаты поиска по номеру или имени. Клик по строке — карточка клиента."
          : "Все клиенты, найденные в звонках, — свежая активность сверху. Риск и оценка — предварительные (scorecard). Клик по строке — карточка: история, риски, похожие звонки."}
      </small>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Поиск: номер или имя клиента"
        style={{ width: 420, padding: "8px 12px", fontSize: 15, boxSizing: "border-box" }}
        autoFocus
      />
      {!searchMode && hits !== null && hits.length > 0 && (
        <div style={{ margin: "10px 0 2px", display: "flex", gap: 8, flexWrap: "wrap" }}>
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              style={
                filter === f.key
                  ? { fontWeight: 600, borderColor: "#2b6cb0", color: "#2b6cb0" }
                  : undefined
              }
            >
              {f.label}
            </button>
          ))}
        </div>
      )}
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {visible.length > 0 && (
        <div style={{ marginTop: 16 }}>
          {visible.map((h) => (
            <div
              key={h.contact_id}
              onClick={() => onPick(h.contact_id)}
              style={{
                display: "flex",
                gap: 14,
                alignItems: "center",
                padding: "10px 12px",
                borderBottom: "1px solid #eee",
                cursor: "pointer",
              }}
            >
              <strong style={{ minWidth: 150 }}>{h.display_name ?? h.phones[0] ?? "—"}</strong>
              <span style={{ flexGrow: 1, color: "#666", fontSize: 14 }}>
                {h.display_name ? h.phones.join(", ") || "номер не привязан" : ""}
              </span>
              {h.risk_score != null && (
                <span
                  title="Риск потери клиента (scorecard)"
                  style={{
                    color: BAND_COLOR[h.risk_band ?? ""] ?? "#888",
                    fontWeight: 600,
                    fontSize: 13,
                    minWidth: 66,
                    textAlign: "right",
                  }}
                >
                  риск {h.risk_score}
                </span>
              )}
              {h.avg_score != null && (
                <span
                  title="Средняя оценка звонков"
                  style={{ color: scoreColor(h.avg_score), fontWeight: 600, fontSize: 13, minWidth: 60, textAlign: "right" }}
                >
                  скор {h.avg_score}
                </span>
              )}
              {h.objections_unhandled > 0 && (
                <span title="Не отработанные возражения" style={{ fontSize: 13, color: "#b58a00" }}>
                  ⚠ {h.objections_unhandled}
                </span>
              )}
              {h.sentiment_last != null && (
                <span
                  title={`Тон клиента: ${h.sentiment_last.toFixed(2)}${h.sentiment_trend != null ? `, тренд ${trendLabel(h.sentiment_trend)}` : ""}`}
                  style={{ minWidth: 46 }}
                >
                  {sentimentEmoji(h.sentiment_last)}
                  {h.sentiment_trend != null && (h.sentiment_trend > 0.1 ? " ↑" : h.sentiment_trend < -0.1 ? " ↓" : "")}
                </span>
              )}
              <small style={{ color: "#888", minWidth: 150, textAlign: "right" }}>
                звонков: {h.calls_total}
                {h.calls_total > 0 && ` · был ${fmtDate(h.last_call_at)}`}
              </small>
            </div>
          ))}
        </div>
      )}
      {hits !== null && visible.length === 0 && (
        <p style={{ color: "#888" }}>
          {searchMode
            ? `Никого не нашли по «${query.trim()}» — проверьте номер или попробуйте другую часть номера`
            : filter !== "all"
              ? "Под этот фильтр никто не подходит"
              : "Пока ни одного клиента — они появятся автоматически с первыми звонками"}
        </p>
      )}
    </div>
  );
}

function ContactCardView({
  contactId,
  onSelectContact,
  onOpenCall,
}: {
  contactId: string;
  onSelectContact: (id: string | null) => void;
  onOpenCall: (id: string) => void;
}) {
  const [card, setCard] = useState<ContactCard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setCard(null);
    setError(null);
    api
      .contactCard(contactId)
      .then(setCard)
      .catch((e) => setError(String(e)));
  }, [contactId]);

  useEffect(load, [load]);

  if (error) {
    return (
      <div>
        <a
          href="#"
          onClick={(e) => {
            e.preventDefault();
            onSelectContact(null);
          }}
          style={{ color: "#06c", fontSize: 14 }}
        >
          ← Все клиенты
        </a>
        <p style={{ color: "crimson" }}>
          Не удалось загрузить карточку: {error}{" "}
          <a href="#" onClick={(e) => { e.preventDefault(); load(); }}>повторить</a>
        </p>
      </div>
    );
  }
  if (!card) {
    return (
      <div>
        <a
          href="#"
          onClick={(e) => {
            e.preventDefault();
            onSelectContact(null);
          }}
          style={{ color: "#06c", fontSize: 14 }}
        >
          ← Все клиенты
        </a>
        <p style={{ color: "#888" }}>Загружаем карточку…</p>
      </div>
    );
  }

  const { stats } = card;
  return (
    <div>
      <a
        href="#"
        onClick={(e) => {
          e.preventDefault();
          onSelectContact(null);
        }}
        style={{ color: "#06c", fontSize: 14 }}
      >
        ← Все клиенты
      </a>
      <h2 style={{ margin: "8px 0 2px" }}>
        {card.contact.display_name ?? "Клиент без имени"}
      </h2>
      <div style={{ color: "#444", fontSize: 15 }}>
        {card.phones.join(", ") || "номер не привязан"}
        {card.company && (
          <span style={{ marginLeft: 10, color: "#666" }}>
            компания: {card.company.name ?? card.company.id}
          </span>
        )}
      </div>

      <div style={{ display: "flex", gap: 16, margin: "16px 0", flexWrap: "wrap" }}>
        <Stat title="Звонков" value={`${stats.calls_total}`} sub={`обработано: ${stats.done_calls}`} />
        <Stat title="Первый звонок" value={fmtDate(stats.first_call_at)} />
        <Stat title="Последний звонок" value={fmtDate(stats.last_call_at)} />
        <Stat
          title="Средняя оценка"
          value={stats.avg_score != null ? String(stats.avg_score) : "—"}
          sub={stats.avg_score != null ? undefined : "нет обработанных звонков"}
        />
        <Stat
          title="Возражений"
          value={`${stats.objections_total}`}
          sub={stats.objections_total > 0 ? `не отработано: ${stats.objections_unhandled}` : undefined}
        />
        <Stat title="Время в разговоре" value={fmtTalk(stats.talk_sec_total)} />
        {stats.sentiment_last != null && (
          <Stat
            title="Тон клиента"
            value={`${sentimentEmoji(stats.sentiment_last)} ${trendLabel(stats.sentiment_trend)}`}
            sub={stats.sentiment_trend != null ? "тренд: последний минус первый" : undefined}
          />
        )}
      </div>

      <NbaBlock card={card} />

      {card.deals.length > 0 && (
        <section style={{ margin: "16px 0" }}>
          <h3 style={{ marginBottom: 4 }}>Сделки</h3>
          {card.deals.map((d) => (
            <div key={d.id} style={{ display: "flex", gap: 12, padding: "6px 12px", borderBottom: "1px solid #eee" }}>
              <span style={{ minWidth: 120 }}>{d.stage ?? "—"}</span>
              <span style={{ color: "#444" }}>
                {d.amount != null ? `${d.amount.toLocaleString("ru-RU")} ${d.currency ?? ""}` : "сумма не указана"}
              </span>
              <span style={{ color: "#888", fontSize: 13 }}>{d.status ?? ""}</span>
            </div>
          ))}
        </section>
      )}

      <RiskBlock card={card} />

      <RepeatBlock card={card} />

      <Timeline card={card} onOpenCall={onOpenCall} />

      <ContactGraph card={card} onOpenCall={onOpenCall} />

      <SimilarBlock card={card} onOpenCall={onOpenCall} />
    </div>
  );
}

function Stat({ title, value, sub }: { title: string; value: string; sub?: string }) {
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: "10px 18px", minWidth: 140 }}>
      <div style={{ color: "#888", fontSize: 12 }}>{title}</div>
      <div style={{ fontSize: 22, fontWeight: 600 }}>{value}</div>
      {sub && <div style={{ color: "#888", fontSize: 12 }}>{sub}</div>}
    </div>
  );
}

function RiskBlock({ card }: { card: ContactCard }) {
  if (!card.risk) {
    return (
      <section style={{ margin: "16px 0", padding: 16, border: "1px solid #ddd", borderRadius: 8 }}>
        <h3 style={{ margin: "0 0 4px" }}>Риск потери клиента</h3>
        <small style={{ color: "#888" }}>Нет звонков — риск не оценивается</small>
      </section>
    );
  }
  const color = BAND_COLOR[card.risk.band] ?? "#888";
  return (
    <section
      style={{
        margin: "16px 0",
        padding: 16,
        border: `1px solid ${color}55`,
        borderRadius: 8,
        background: `${color}0d`,
      }}
    >
      <h3 style={{ margin: "0 0 8px" }}>
        Риск потери клиента:{" "}
        <strong style={{ color }}>
          {card.risk.score} / 100 — {BAND_RU[card.risk.band] ?? card.risk.band}
        </strong>{" "}
        <small style={{ color: "#888" }}>(предварительная оценка)</small>
      </h3>
      {card.risk.factors.slice(0, 4).map((f) => (
        <div key={f.feature} style={{ margin: "4px 0", display: "flex", gap: 8 }}>
          <span style={{ minWidth: 44, fontWeight: 600, color: f.contribution > 0 ? "#c22" : "#0a7d33" }}>
            +{f.contribution}
          </span>
          <span>
            <b>{FEATURE_RU[f.feature] ?? f.feature}:</b> {f.description}
          </span>
        </div>
      ))}
      <small style={{ color: "#888" }}>
        Оценка станет точнее по мере накопления исходов сделок
      </small>
    </section>
  );
}

function RepeatBlock({ card }: { card: ContactCard }) {
  // Root-Cause «Unresolved Repeat» (DoD М3): одно и то же возражение в
  // нескольких звонках без успешной отработки — клиент ходит по кругу.
  if (!card.repeat || card.repeat.items.length === 0) return null;
  return (
    <section
      style={{
        margin: "16px 0",
        padding: 16,
        border: "1px solid #b58a0055",
        borderRadius: 8,
        background: "#b58a000d",
      }}
    >
      <h3 style={{ margin: "0 0 4px" }}>Повторяющиеся проблемы</h3>
      <small style={{ color: "#888", display: "block", marginBottom: 6 }}>
        Одно и то же возражение в нескольких звонках, и каждый раз без успеха —
        разговор не продвигается. Стоит сменить подход или эскалировать.
      </small>
      {card.repeat.items.map((r) => (
        <div key={r.type} style={{ display: "flex", gap: 10, margin: "4px 0", alignItems: "baseline" }}>
          <strong style={{ color: "#b58a00" }}>{ru(OBJECTION_RU, r.type)}</strong>
          <span style={{ fontSize: 13, color: "#444" }}>
            прозвучало в {r.calls} звонках; последний раз —{" "}
            {ru(RESPONSE_RU, r.last_status, "не отработано")}
          </span>
          <small style={{ color: "#888" }}>{fmtDate(r.last_at)}</small>
        </div>
      ))}
    </section>
  );
}

function NbaBlock({ card }: { card: ContactCard }) {
  // Next Best Action (DoD М3): до трёх рекомендаций по правилам на
  // риске, повторах и последнем звонке. Нет звонков — блок не показываем.
  if (!card.nba || card.nba.items.length === 0) return null;
  return (
    <section
      style={{
        margin: "16px 0",
        padding: 16,
        border: "1px solid #2b6cb055",
        borderRadius: 8,
        background: "#2b6cb00d",
      }}
    >
      <h3 style={{ margin: "0 0 4px" }}>Что сделать сейчас</h3>
      <small style={{ color: "#888", display: "block", marginBottom: 6 }}>
        Рекомендации по правилам: риск, повторяющиеся проблемы и последний разговор.
      </small>
      {card.nba.items.map((r, i) => (
        <div key={i} style={{ display: "flex", gap: 10, margin: "4px 0", alignItems: "baseline" }}>
          <strong style={{ color: "#2b6cb0" }}>{i + 1}. {r.action}</strong>
          <span style={{ fontSize: 13, color: "#444" }}>— {r.reason}</span>
        </div>
      ))}
    </section>
  );
}

type TimelineEntry =
  | { kind: "call"; at: string; call: CardCall }
  | { kind: "interaction"; at: string; it: ContactCard["interactions"][number] };

const KIND_GLYPH: Record<string, string> = {
  email: "✉",
  chat: "💬",
  meeting: "📅",
  sms: "✱",
};

// Пауза между соседними событиями цепочки — «через 2 дн.», «через 3 ч»
function gapLabel(prevIso: string, curIso: string): string | null {
  const dt = (new Date(curIso).getTime() - new Date(prevIso).getTime()) / 1000;
  if (dt <= 0) return null;
  if (dt >= 86400) return `через ${Math.round(dt / 86400)} дн.`;
  if (dt >= 3600) return `через ${Math.round(dt / 3600)} ч`;
  if (dt >= 60) return `через ${Math.round(dt / 60)} мин`;
  return null;
}

function Timeline({ card, onOpenCall }: { card: ContactCard; onOpenCall: (id: string) => void }) {
  // От раннего к позднему: цепочка читается сверху вниз, #1 — первый звонок
  const entries: TimelineEntry[] = [
    ...card.calls.map((call): TimelineEntry => ({ kind: "call", at: call.started_at, call })),
    ...card.interactions.map((it): TimelineEntry => ({ kind: "interaction", at: it.occurred_at, it })),
  ].sort((a, b) => (a.at < b.at ? -1 : 1));

  return (
    <section style={{ margin: "16px 0" }}>
      <h3 style={{ marginBottom: 0 }}>История общения</h3>
      <small style={{ color: "#888", display: "block", marginBottom: 6 }}>
        Цепочка от первого звонка к последнему — сверху вниз, номер шага в кружке.
        Пауза перед событием подписана между шагами. Клик по звонку — открыть разбор.
      </small>
      {entries.length === 0 && <p style={{ color: "#888" }}>Общения пока не было</p>}
      {entries.map((e, i) => {
        const isCall = e.kind === "call";
        const key = isCall ? e.call.id : e.it.id;
        const isLast = i === entries.length - 1;
        const prev = i > 0 ? entries[i - 1] : null;
        const gap = prev ? gapLabel(prev.at, e.at) : null;
        const dotColor = isCall ? scoreColor(e.call.score_total) : "#8a94a6";
        const failed = isCall && e.call.state === "failed";
        return (
          <div key={key}>
            {gap && (
              <div style={{ display: "flex" }}>
                <div style={{ width: 46, display: "flex", justifyContent: "center", flexShrink: 0 }}>
                  <div style={{ width: 2, background: "#dbe2ec" }} />
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "2px 0" }}>
                  <span style={{ color: "#9aa7b8", fontSize: 12 }}>↓</span>
                  <small style={{ color: "#9aa7b8", fontSize: 12 }}>{gap}</small>
                </div>
              </div>
            )}
            <div style={{ display: "flex" }}>
              <div style={{ width: 46, display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                <div style={{ width: 2, flexGrow: 1, background: i === 0 ? "transparent" : "#dbe2ec" }} />
                <div
                  style={{
                    width: 24,
                    height: 24,
                    borderRadius: "50%",
                    background: isLast || failed ? dotColor : "#fff",
                    border: `2px solid ${dotColor}`,
                    color: isLast || failed ? "#fff" : dotColor,
                    fontSize: 10,
                    fontWeight: 700,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                    boxSizing: "border-box",
                  }}
                  title={isCall ? `Шаг цепочки #${(e.call.chain_depth ?? 0) + 1}` : undefined}
                >
                  {isCall ? `#${(e.call.chain_depth ?? 0) + 1}` : ru(KIND_GLYPH, e.it.kind, "•")}
                </div>
                <div style={{ width: 2, flexGrow: 1, background: isLast ? "transparent" : "#dbe2ec" }} />
              </div>
              {isCall ? (
                <div
                  onClick={() => onOpenCall(e.call.id)}
                  style={{
                    flexGrow: 1,
                    display: "flex",
                    gap: 12,
                    alignItems: "center",
                    padding: "8px 12px",
                    margin: "3px 0",
                    background: isLast ? "#f4f8ff" : "#fbfcfe",
                    border: `1px solid ${isLast ? "#c9dcf5" : "#e8edf4"}`,
                    borderRadius: 8,
                    cursor: "pointer",
                    flexWrap: "wrap",
                  }}
                >
                  <small style={{ color: "#888", minWidth: 140 }}>
                    {new Date(e.call.started_at).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" })}
                  </small>
                  <span style={{ minWidth: 110 }}>{ru(DIRECTION_RU, e.call.direction)}</span>
                  <small>{fmtDur(e.call.duration_sec)}</small>
                  {e.call.duration_sec != null && e.call.duration_sec < 15 && (
                    <span
                      title="Короткий звонок — вне семантического анализа"
                      style={{ fontSize: 12, background: "#fdf2e0", color: "#8a6d3b", borderRadius: 10, padding: "2px 8px" }}
                    >
                      короткий
                    </span>
                  )}
                  <StateBadge state={e.call.state} />
                  {e.call.score_total != null && (
                    <span style={{ fontWeight: 600, color: scoreColor(e.call.score_total) }}>
                      оценка {e.call.score_total}
                    </span>
                  )}
                  {e.call.sentiment != null && (
                    <span title={`Тон клиента: ${e.call.sentiment.toFixed(2)}`}>
                      {sentimentEmoji(e.call.sentiment)}
                    </span>
                  )}
                  {e.call.objections.map((o, j) => (
                    <span
                      key={j}
                      style={{
                        fontSize: 12,
                        background: "#f0f4ff",
                        borderRadius: 10,
                        padding: "2px 8px",
                        color: "#345",
                      }}
                      title={ru(RESPONSE_RU, o.response_status, "статус неизвестен")}
                    >
                      {ru(OBJECTION_RU, o.type)}
                      {o.response_status && o.response_status !== "handled_success" ? " ⚠" : ""}
                    </span>
                  ))}
                  <small style={{ color: "#06c", marginLeft: "auto" }}>открыть звонок →</small>
                </div>
              ) : (
                <div
                  style={{
                    flexGrow: 1,
                    display: "flex",
                    gap: 12,
                    alignItems: "baseline",
                    padding: "8px 12px",
                    margin: "3px 0",
                    background: "#fafbfd",
                    border: "1px solid #eceff4",
                    borderRadius: 8,
                  }}
                >
                  <small style={{ color: "#888", minWidth: 140 }}>
                    {new Date(e.it.occurred_at).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" })}
                  </small>
                  <span style={{ minWidth: 110 }}>{ru(KIND_RU, e.it.kind, e.it.kind)}</span>
                  <span style={{ color: "#444", fontSize: 13 }}>
                    {typeof e.it.payload?.subject === "string"
                      ? e.it.payload.subject
                      : typeof e.it.payload?.summary === "string"
                        ? e.it.payload.summary
                        : ""}
                  </span>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </section>
  );
}

function ContactGraph({ card, onOpenCall }: { card: ContactCard; onOpenCall: (id: string) => void }) {
  const W = 820;
  const H = 320;
  const cx = W / 2;
  const contactY = 56;
  const midY = 160;
  const callsY = 272;

  const calls = card.calls.slice(0, 12);
  const hiddenCalls = card.calls.length - calls.length;
  const phoneNodes = card.phones.slice(0, 3).map((p, i, arr) => ({
    e164: p,
    x: arr.length === 1 ? W * 0.18 : W * 0.1 + (i * W * 0.16) / Math.max(arr.length - 1, 1),
    y: midY,
  }));
  const companyX = W * 0.84;
  const callX = (i: number) =>
    calls.length === 1 ? cx : 40 + (i * (W - 80)) / (calls.length - 1);

  return (
    <section style={{ margin: "16px 0" }}>
      <h3 style={{ marginBottom: 0 }}>Граф связей</h3>
      <small style={{ color: "#888", display: "block", marginBottom: 6 }}>
        Клиент, его номера и звонки (кружок — звонок, цвет — оценка). Клик по кружку открывает звонок.
        Компании и сделки появятся, когда подключена CRM.
      </small>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", border: "1px solid #eee", borderRadius: 8, background: "#fbfcfe" }}
      >
        {phoneNodes.map((p) => (
          <g key={p.e164}>
            <line x1={cx} y1={contactY} x2={p.x} y2={p.y} stroke="#b8c4d4" />
            <circle cx={p.x} cy={p.y} r={9} fill="#fff" stroke="#5b7a9d" strokeWidth={2} />
            <text x={p.x} y={p.y + 28} textAnchor="middle" fontSize={11} fill="#456">{p.e164}</text>
          </g>
        ))}
        {card.company && (
          <g>
            <line x1={cx} y1={contactY} x2={companyX} y2={midY} stroke="#b8c4d4" />
            <rect x={companyX - 34} y={midY - 14} width={68} height={28} rx={6} fill="#fff" stroke="#8a6fc0" strokeWidth={2} />
            <text x={companyX} y={midY + 4} textAnchor="middle" fontSize={10} fill="#553">
              {(card.company.name ?? "компания").slice(0, 10)}
            </text>
          </g>
        )}
        {calls.map((c, i) => (
          <g key={c.id} onClick={() => onOpenCall(c.id)} style={{ cursor: "pointer" }}>
            <line x1={cx} y1={contactY} x2={callX(i)} y2={callsY} stroke="#dbe2ec" />
            <circle cx={callX(i)} cy={callsY} r={9} fill="#fff" stroke={scoreColor(c.score_total)} strokeWidth={2.5} />
            {c.score_total != null && (
              <text x={callX(i)} y={callsY + 4} textAnchor="middle" fontSize={9} fill="#345">
                {c.score_total}
              </text>
            )}
            <text x={callX(i)} y={callsY + 26} textAnchor="middle" fontSize={10} fill="#889">
              {new Date(c.started_at).toLocaleDateString("ru-RU")}
            </text>
          </g>
        ))}
        <circle cx={cx} cy={contactY} r={22} fill="#e8f1ff" stroke="#2b6cb0" strokeWidth={2} />
        <text x={cx} y={contactY - 32} textAnchor="middle" fontSize={12} fontWeight={600} fill="#234">
          {(card.contact.display_name ?? "Клиент").slice(0, 24)}
        </text>
        {hiddenCalls > 0 && (
          <text x={W - 12} y={callsY - 18} textAnchor="end" fontSize={11} fill="#889">
            ещё звонков: {hiddenCalls}
          </text>
        )}
      </svg>
    </section>
  );
}

function SimilarBlock({ card, onOpenCall }: { card: ContactCard; onOpenCall: (id: string) => void }) {
  if (!card.similar || card.similar.items.length === 0) return null;
  const base = card.calls.find((c) => c.id === card.similar?.base_call_id);
  return (
    <section style={{ margin: "16px 0" }}>
      <h3 style={{ marginBottom: 0 }}>Похожие звонки</h3>
      <small style={{ color: "#888", display: "block", marginBottom: 6 }}>
        Сходство по смыслу разговора со звонком от {fmtDate(base?.started_at ?? null)}
        {base?.started_at
          ? ` в ${new Date(base.started_at).toLocaleTimeString("ru-RU", { timeStyle: "short" })}`
          : ""}
        . Клик — открыть звонок.
      </small>
      {card.similar.items.map((s) => (
        <div
          key={s.call_id}
          onClick={() => onOpenCall(s.call_id)}
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
          {s.similarity >= 0.995 && <small style={{ color: "#c22" }}>возможно, дубль записи</small>}
        </div>
      ))}
    </section>
  );
}
