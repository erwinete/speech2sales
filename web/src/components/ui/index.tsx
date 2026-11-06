/** Базовые UI-примитивы дизайн-системы (ТЗ §5.3, офлайн: SVG-иконки вместо lucide). */
import React from "react";

const ICONS: Record<string, React.ReactNode> = {
  dashboard: <><rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/></>,
  users: <><circle cx="9" cy="8" r="3.5"/><path d="M2.5 19c.8-3 3.4-5 6.5-5s5.7 2 6.5 5"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14.5c2.5.4 4.4 2 5 4.5"/></>,
  phone: <path d="M5 4h4l2 5-2.5 1.5c1.2 2.4 3.1 4.3 5.5 5.5L15.5 13l5 2v4c0 .6-.4 1-1 1C10.6 20 4 13.4 4 5c0-.6.4-1 1-1z"/>,
  contacts: <><circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4.2-6 8-6s7 2 8 6"/></>,
  plug: <path d="M9 3v6M15 3v6M7 9h10v3a5 5 0 0 1-5 5 5 5 0 0 1-5-5V9zM12 17v4"/>,
  settings: <><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7 7 0 0 0-2-1.2L14.2 3H9.8l-.4 2.7a7 7 0 0 0-2 1.2l-2.3-1-2 3.4 2 1.5a7 7 0 0 0 0 2.4l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 2 1.2l.4 2.7h4.4l.4-2.7a7 7 0 0 0 2-1.2l2.3 1 2-3.4-2-1.5c.06-.4.1-.8.1-1.2z"/></>,
  coach: <><path d="M12 3 2 8l10 5 10-5-10-5z"/><path d="M6 10.5V15c0 1.7 2.7 3 6 3s6-1.3 6-3v-4.5"/></>,
  play: <path d="M7 5v14l12-7z"/>,
  pause: <><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></>,
  upload: <path d="M12 16V4m0 0 4 4m-4-4-4 4M4 20h16"/>,
  search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m20 20-4.5-4.5"/></>,
  logout: <path d="M9 4H5v16h4M14 8l4 4-4 4M8 12h10"/>,
  refresh: <path d="M20 11a8 8 0 1 0-2.3 5.3M20 5v6h-6"/>,
  alert: <><path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4m0 3v.5"/></>,
  sparkles: <><path d="M12 3.5 13.6 8l4.4 1.6L13.6 11.2 12 15.7l-1.6-4.5L6 9.6 10.4 8 12 3.5z"/><path d="M18.5 14.5 19.3 17l2.2.8-2.2.8-.8 2.4-.8-2.4-2.2-.8 2.2-.8.8-2.5z"/><path d="M5 14l.7 2.1L7.8 17l-2.1.8L5 20l-.7-2.2L2.2 17l2.1-.9L5 14z"/></>,
  copy: <><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></>,
  download: <path d="M12 4v12m0 0 4-4m-4 4-4-4M4 20h16"/>,
  shield: <><path d="M12 3 5 6v6c0 4.4 3 8.4 7 9.5 4-1.1 7-5.1 7-9.5V6l-7-3z"/><path d="m9 12 2 2 4-4"/></>,
  bot: <><rect x="4" y="8" width="16" height="11" rx="3"/><path d="M12 8V4m-4 8h.01M16 12h.01M9 16h6"/></>,
};

export function Icon({ name, size = 16 }: { name: keyof typeof ICONS | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      {ICONS[name] ?? null}
    </svg>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: "success" | "warning" | "danger" | "brand" | "violet" | "neutral"; children: React.ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function EmptyState({ icon = "search", text, action }: { icon?: string; text: string; action?: React.ReactNode }) {
  return (
    <div className="empty">
      <div className="icon"><Icon name={icon} size={28} /></div>
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
