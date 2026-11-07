/** UI-примитивы (ТЗ v6.0): все индикаторы — собственные сгенерированные глифы
    через BrutalistGlyph; старые имена Icon маппятся на новые изображения. */
import React from "react";
import { BrutalistGlyph, type GlyphName } from "./BrutalistGlyph";

export type { GlyphName };
export { BrutalistGlyph };
export { SlabButton, type SlabVariant } from "./SlabButton";
export { RailToggle } from "./RailToggle";
export { StepSelect, type StepOption } from "./StepSelect";
export { SegmentedMatrix } from "./SegmentedMatrix";
export { MeterBar, type MeterTone } from "./MeterBar";

/** Маппинг прежних логических имён на собственные изображения-глифы. */
const GLYPH_MAP: Record<string, GlyphName> = {
  dashboard: "nav-dashboard",
  users: "nav-reps",
  phone: "channel-call",
  contacts: "nav-customer",
  plug: "nav-settings",
  settings: "nav-settings",
  coach: "nav-reps",
  play: "ctrl-play",
  pause: "ctrl-pause",
  upload: "ctrl-upload",
  search: "status-ok",
  logout: "ctrl-sort-desc",
  refresh: "ctrl-sort-asc",
  alert: "status-alert",
  sparkles: "nav-llm",
  copy: "ctrl-copy",
  download: "ctrl-upload",
  shield: "status-pii",
  bot: "nav-llm",
};

export function Icon({ name, size = 16, label }: { name: string; size?: number; label?: string }) {
  const glyph = GLYPH_MAP[name] ?? "status-ok";
  return <BrutalistGlyph name={glyph} size={size} label={label} />;
}

export function Badge({ tone = "neutral", children }: { tone?: "success" | "warning" | "danger" | "brand" | "violet" | "neutral"; children: React.ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function EmptyState({ icon = "search", text, action }: { icon?: string; text: string; action?: React.ReactNode }) {
  return (
    <div className="empty">
      <div className="icon"><Icon name={icon} size={24} /></div>
      <div>{text}</div>
      {action && <div style={{ marginTop: 10 }}>{action}</div>}
    </div>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return <div>{Array.from({ length: rows }).map((_, i) => <div key={i} className="skeleton" style={{ width: `${90 - i * 12}%` }} />)}</div>;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  React.useEffect(() => {
    const onEsc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <h3>{title}</h3>
        {children}
      </div>
    </div>
  );
}

export function Tabs({ tabs, active, onChange }: { tabs: { key: string; label: string }[]; active: string; onChange: (key: string) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.key} role="tab" aria-selected={active === t.key}
          className={`tab ${active === t.key ? "active" : ""}`} onClick={() => onChange(t.key)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function scoreTone(score: number | null | undefined): "success" | "warning" | "danger" | "neutral" {
  if (score == null) return "neutral";
  if (score >= 65) return "success";
  if (score >= 40) return "warning";
  return "danger";
}

export function bandTone(band: string | null | undefined): "success" | "warning" | "danger" | "neutral" {
  if (band === "low") return "success";
  if (band === "medium") return "warning";
  if (band === "high") return "danger";
  return "neutral";
}
