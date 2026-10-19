import { useState } from "react";
import type { CallFilters } from "../api";

// Фильтры дашборда (doc 08 §4.1): пресеты периода, календарь (с/по),
// длительность пресетом или своим значением в секундах.



const PERIODS = [
  { label: "7 дней", days: 7 },
  { label: "30 дней", days: 30 },
  { label: "90 дней", days: 90 },
];

const DUR_PRESETS = [
  { label: "Любая", min: null as number | null, max: null as number | null },
  { label: "до 1 мин", min: null as number | null, max: 59 },
  { label: "1–5 мин", min: 60, max: 300 },
  { label: "5–15 мин", min: 301, max: 900 },
  { label: "15+ мин", min: 901, max: null as number | null },
];

function isoDaysAgo(days: number): string {
  const d = new Date(Date.now() - days * 86400000);
  return d.toISOString().slice(0, 10);
}
const todayIso = () => new Date().toISOString().slice(0, 10);

export default function FilterBar({
  filters,
  onChange,
}: {
  filters: CallFilters;
  onChange: (f: CallFilters) => void;
}) {
  const [customDur, setCustomDur] = useState(false);
  const presetActive = PERIODS.some(
    (p) => filters.dateFrom === isoDaysAgo(p.days - 1) && filters.dateTo === todayIso(),
  );

  const setPreset = (days: number) =>
    onChange({ ...filters, dateFrom: isoDaysAgo(days - 1), dateTo: todayIso() });

  return (
    <div style={{ border: "1px solid #e5e5e5", borderRadius: 8, padding: "10px 14px", margin: "12px 0" }}>
      <div style={{ display: "flex", gap: 20, alignItems: "flex-end", flexWrap: "wrap" }}>
        <div>
          <small style={{ color: "#888", display: "block", marginBottom: 2 }}>Период</small>
          {PERIODS.map((p) => (
            <button
              key={p.days}
              onClick={() => setPreset(p.days)}
              style={{
                marginRight: 4, padding: "4px 10px", cursor: "pointer",
                border: "1px solid", borderRadius: 6,
                background: presetActive && filters.dateFrom === isoDaysAgo(p.days - 1) ? "#2f6fed22" : "#fff",
                borderColor: presetActive && filters.dateFrom === isoDaysAgo(p.days - 1) ? "#2f6fed" : "#ccc",
              }}
            >
              {p.label}
            </button>
          ))}
          <button
            onClick={() => onChange({ ...filters, dateFrom: undefined, dateTo: undefined })}
            style={{
              marginRight: 4, padding: "4px 10px", cursor: "pointer",
              border: "1px solid", borderRadius: 6,
              background: !filters.dateFrom && !filters.dateTo ? "#2f6fed22" : "#fff",
              borderColor: !filters.dateFrom && !filters.dateTo ? "#2f6fed" : "#ccc",
            }}
          >
            Всё время
          </button>
        </div>

        <div>
          <small style={{ color: "#888", display: "block", marginBottom: 2 }}>или календарём (с / по)</small>
          <input
            type="date"
            value={filters.dateFrom ?? ""}
            onChange={(e) => onChange({ ...filters, dateFrom: e.target.value || undefined })}
            style={{ padding: "4px 8px", border: "1px solid #ccc", borderRadius: 6, marginRight: 4 }}
          />
          <input
            type="date"
            value={filters.dateTo ?? ""}
            onChange={(e) => onChange({ ...filters, dateTo: e.target.value || undefined })}
            style={{ padding: "4px 8px", border: "1px solid #ccc", borderRadius: 6 }}
          />
        </div>

        <div>
          <small style={{ color: "#888", display: "block", marginBottom: 2 }}>Длительность звонка</small>
          <select
            value={DUR_PRESETS.findIndex(
              (d) =>
                d.min === (filters.durationMin ?? null) &&
                d.max === (filters.durationMax ?? null),
            ) || ""}
            onChange={(e) => {
              const i = Number(e.target.value);
              if (DUR_PRESETS[i]) {
                onChange({ ...filters, durationMin: DUR_PRESETS[i].min, durationMax: DUR_PRESETS[i].max });
                setCustomDur(false);
              }
            }}
            style={{ padding: "4px 8px", border: "1px solid #ccc", borderRadius: 6, marginRight: 4 }}
          >
            <option value="">— выбрать —</option>
            {DUR_PRESETS.map((d, i) => (
              <option key={d.label} value={i}>{d.label}</option>
            ))}
          </select>
        </div>

        <div>
          <small style={{ color: "#888", display: "block", marginBottom: 2 }}>Своё (секунды: от / до)</small>
          {customDur || (filters.durationMin != null && !DUR_PRESETS.some((d) => d.min === filters.durationMin && d.max === filters.durationMax)) ? (
            <span>
              <input
                type="number"
                min={0}
                placeholder="от"
                value={filters.durationMin ?? ""}
                onChange={(e) =>
                  onChange({ ...filters, durationMin: e.target.value ? Number(e.target.value) : null })
                }
                style={{ width: 80, padding: "4px 8px", border: "1px solid #ccc", borderRadius: 6, marginRight: 4 }}
              />
              <input
                type="number"
                min={0}
                placeholder="до"
                value={filters.durationMax ?? ""}
                onChange={(e) =>
                  onChange({ ...filters, durationMax: e.target.value ? Number(e.target.value) : null })
                }
                style={{ width: 80, padding: "4px 8px", border: "1px solid #ccc", borderRadius: 6 }}
              />
            </span>
          ) : (
            <button
              onClick={() => setCustomDur(true)}
              style={{ padding: "4px 10px", cursor: "pointer", border: "1px solid #ccc", borderRadius: 6 }}
            >
              Своё значение…
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
