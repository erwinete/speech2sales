import { useEffect, useState } from "react";
import type { CallDetailRow } from "../api";

// Карточка «Риск контакта» (M5 scorecard, doc 08 §1): score/band + факторы-вклады.
// 404 (нет звонков) — блок не показывается.

interface RiskFactor {
  feature: string;
  contribution: number;
  description: string;
}

interface Risk {
  score: number;
  band: string;
  factors: RiskFactor[];
  model_id: string;
}

const BAND_COLOR: Record<string, string> = {
  low: "#0a7d33",
  medium: "#b58a00",
  high: "#c22",
};
const BAND_RU: Record<string, string> = { low: "низкий", medium: "средний", high: "высокий" };
const FEATURE_RU: Record<string, string> = {
  days_silence: "Молчание (дней с последнего звонка)",
  unanswered_ratio: "Пропущенные",
  unhandled_ratio: "Неотработанные возражения",
  avg_score: "Качество звонков",
};

export default function ContactRisk({
  call,
  onOpenContact,
}: {
  call: CallDetailRow;
  onOpenContact?: (id: string) => void;
}) {
  const [risk, setRisk] = useState<Risk | null>(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    let alive = true;
    if (!call.contact_id) {
      setHidden(true);
      return;
    }
    fetch(`/api/v1/contacts/${call.contact_id}/risk`, {
      headers: { "X-Api-Key": localStorage.getItem("polylog_token") ?? "dev-insecure-token" },
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((r: Risk) => {
        if (alive) setRisk(r);
      })
      .catch(() => {
        if (alive) setHidden(true);
      });
    return () => {
      alive = false;
    };
  }, [call.contact_id]);

  if (hidden || !risk) return null;
  const color = BAND_COLOR[risk.band] ?? "#888";

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
        Риск контакта:{" "}
        <strong style={{ color }}>
          {risk.score} / 100 — {BAND_RU[risk.band] ?? risk.band}
        </strong>{" "}
        <small style={{ color: "#888" }}>(предварительная оценка)</small>
      </h3>
      {risk.factors.slice(0, 3).map((f) => (
        <div key={f.feature} style={{ margin: "4px 0", display: "flex", gap: 8 }}>
          <span style={{ minWidth: 60, fontWeight: 600, color: f.contribution > 0 ? "#c22" : "#0a7d33" }}>
            +{f.contribution}
          </span>
          <span>
            <b>{FEATURE_RU[f.feature] ?? f.feature}:</b> {f.description}
          </span>
        </div>
      ))}
      <small style={{ color: "#888" }}>
        Предварительная оценка по правилам. Станет точнее по мере накопления исходов сделок
      </small>
      {onOpenContact && call.contact_id && (
        <div style={{ marginTop: 8 }}>
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              onOpenContact(call.contact_id as string);
            }}
            style={{ color: "#06c", fontSize: 14 }}
          >
            Открыть карточку клиента →
          </a>
        </div>
      )}
    </section>
  );
}
