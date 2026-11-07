/** AppShell + модульный роутер (History API, ТЗ §5.1 офлайн-режим) +
    страницы приложения. */
import React from "react";
import { AuthProvider, ToastProvider, useAuth, useToast } from "./context/app";
import { api } from "./api";
import { SlabButton } from "./components/ui";
import { BrutalistGlyph, type GlyphName } from "./components/ui/BrutalistGlyph";
import DashboardPage from "./pages/DashboardPage";
import CallDetailPage from "./pages/CallDetailPage";
import Customer360Page from "./pages/Customer360Page";
import ManagersAnalyticsPage from "./pages/ManagersAnalyticsPage";
import ConnectorsPage from "./pages/ConnectorsPage";
import UsersPage from "./pages/UsersPage";
import SettingsPage from "./pages/SettingsPage";
import AiLabPage from "./pages/AiLabPage";

type Route = { path: string; query: URLSearchParams };

function parseLocation(): Route {
  const raw = window.location.pathname.replace(/^\/+/, "");
  const path = raw === "" ? "dashboard" : raw;
  return { path, query: new URLSearchParams(window.location.search) };
}

/** Навигация по History API (DEF-07: доступна компонентам вне App). */
export function navigate(path: string) {
  window.history.pushState({}, "", path.startsWith("/") ? path : `/${path}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

const NAV_ITEMS: { path: string; index: string; glyph: GlyphName; label: string; roles?: string[] }[] = [
  { path: "dashboard", index: "01", glyph: "nav-dashboard", label: "Сводка и звонки" },
  { path: "contacts", index: "02", glyph: "nav-customer", label: "Клиент 360" },
  { path: "managers", index: "03", glyph: "nav-reps", label: "Команда и коучинг" },
  { path: "ai-lab", index: "04", glyph: "nav-llm", label: "ИИ-Анализ / MCP",
    roles: ["admin", "supervisor", "analyst"] },
  { path: "connectors", index: "05", glyph: "nav-settings", label: "Коннекторы",
    roles: ["admin", "supervisor", "analyst"] },
  { path: "users", index: "06", glyph: "nav-reps", label: "Пользователи",
    roles: ["admin", "supervisor", "analyst"] },
  { path: "settings", index: "07", glyph: "nav-settings", label: "Система и 152-ФЗ",
    roles: ["admin", "supervisor", "analyst"] },
];

/** Переключатель приглушённой темы stone и ash (ТЗ v6.0 §1.2). */
function useTheme(): [string, () => void] {
  const [theme, setTheme] = React.useState<"stone" | "ash">(
    () => (localStorage.getItem("polylog_theme") as "stone" | "ash") || "stone",
  );
  React.useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("polylog_theme", theme);
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "stone" ? "ash" : "stone"))];
}

function Sidebar({ route, callsCount }: { route: Route; callsCount: number | null }) {
  const { user } = useAuth();
  const allowed = (roles?: string[]) =>
    !roles || user?.role === "admin" || user?.role === "supervisor" || user?.role === "analyst" || user?.is_service;
  return (
    <aside className="sidebar">
      <div className="group-label">Аналитика</div>
      {NAV_ITEMS.map((item) =>
        !allowed(item.roles) ? null : (
          <a
            key={item.path}
            className={`nav-item ${route.path === item.path ? "active" : ""}`}
            href={`/${item.path}`}
            onClick={(e) => { e.preventDefault(); navigate(item.path); }}
          >
            <span className="nav-index">{item.index}</span>
            <BrutalistGlyph name={item.glyph} size={16} />
            {item.label}
            {item.path === "dashboard" && callsCount != null && <span className="count">{callsCount}</span>}
          </a>
        ),
      )}
      <div className="nav-footer">
        <div style={{ fontWeight: 600, fontSize: 12 }}>{user?.display_name ?? "…"}</div>
        <div className="muted" style={{ fontSize: 11 }}>{user?.email}</div>
        {user && <span className={`badge ${user.role === "admin" ? "violet" : "brand"}`}>{user.role}</span>}
      </div>
    </aside>
  );
}

function UploadCallModal({ onClose, onDone }: { onClose: () => void; onDone: (callId: string) => void }) {
  const { push } = useToast();
  const [busy, setBusy] = React.useState(false);
  const [file, setFile] = React.useState<File | null>(null);
  const [direction, setDirection] = React.useState("outbound");
  const [from, setFrom] = React.useState("101");
  const [to, setTo] = React.useState("");

  const submit = async () => {
    if (!file || !to) { push("error", "Выберите файл и укажите номер клиента"); return; }
    setBusy(true);
    try {
      // UI-01/R-01: загрузка через api.ts; request() не ставит Content-Type для FormData
      const form = new FormData();
      form.set("file", file);
      form.set("direction", direction);
      form.set("phone_from", from);
      form.set("phone_to", to);
      const body = await api.uploadCall(form);
      push("success", body.created ? "Звонок загружен и обработан" : "Дубликат по содержимому");
      onDone(body.call.id);
    } catch (e) {
      push("error", `Ошибка загрузки: ${String(e).slice(0, 120)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Загрузить звонок</h3>
        <div className="form-row">
          <label>Аудиофайл (wav/mp3/ogg/m4a, до 200 МБ)</label>
          <input type="file" accept=".wav,.mp3,.ogg,.m4a" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>
        <div className="form-row">
          <label>Направление</label>
          <select value={direction} onChange={(e) => setDirection(e.target.value)}>
            <option value="outbound">Исходящий</option>
            <option value="inbound">Входящий</option>
            <option value="internal">Внутренний</option>
          </select>
        </div>
        <div className="form-row">
          <label>Внутренний номер менеджера</label>
          <input value={from} onChange={(e) => setFrom(e.target.value)} placeholder="101" />
        </div>
        <div className="form-row">
          <label>Телефон клиента</label>
          <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="+79001234567" />
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
          <button onClick={onClose}>Отмена</button>
          <button className="primary" disabled={busy} onClick={() => void submit()}>
            {busy ? "Загрузка и разбор…" : "Загрузить"}
          </button>
        </div>
      </div>
    </div>
  );
}

function App() {
  const [route, setRoute] = React.useState<Route>(parseLocation);
  const [callsCount, setCallsCount] = React.useState<number | null>(null);
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [theme, toggleTheme] = useTheme();
  React.useEffect(() => {
    const sync = () => setRoute(parseLocation());
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  const go = (path: string) => {
    navigate(path);
    setRoute(parseLocation());
  };

  const page = route.path.split("/")[0];
  const param = route.path.split("/")[1];
  const title = NAV_ITEMS.find((i) => i.path === page)?.label
    ?? (page === "calls" ? "Разбор звонка" : "Полилог");

  return (
    <div className="app-shell">
      {/* System Header Bar (ТЗ v6.0 §4.1): бренд, телеметрия, действия */}
      <header className="sys-header">
        <div className="sys-header__brand">
          Полилог <span className="muted">// речевая аналитика</span>
        </div>
        <div className="sys-header__telemetry">
          <div className="sys-header__cell">
            <BrutalistGlyph name="nav-calls" size={14} /> Звонков в базе: <b>{callsCount ?? "…"}</b>
          </div>
          <div className="sys-header__cell">
            <BrutalistGlyph name="nav-llm" size={14} /> Конвейер ASR / RuBERT: <b>локальный</b>
          </div>
          <div className="sys-header__cell">
            <BrutalistGlyph name="status-pii" size={14} /> Маскирование ПДн: <b>активно</b>
          </div>
        </div>
        <div className="sys-header__actions">
          <SlabButton glyph="ctrl-upload" indexTag="WAV/MP3" onClick={() => setUploadOpen(true)}>
            Загрузить запись
          </SlabButton>
          <SlabButton glyph="ctrl-theme" indexTag={theme.toUpperCase()} onClick={toggleTheme} />
        </div>
      </header>

      <div className="sys-body">
      <Sidebar route={route} callsCount={callsCount} />
      <div className="main">
        <div className="topbar">
          <h2 style={{ margin: 0 }}>{title}</h2>
          <div className="spacer" />
        </div>

        {page === "dashboard" && (
          <DashboardPage
            route={route}
            onCallsLoaded={(n) => setCallsCount(n)}
            onOpenCall={(id) => go(`calls/${id}`)}
            onOpenContacts={() => go("contacts")}
          />
        )}
        {page === "calls" && param && (
          <CallDetailPage callId={param} onBack={() => go("dashboard")} onOpenCall={(id) => go(`calls/${id}`)} onOpenContact={() => go("contacts")} onOpenAiLab={(q) => go(`ai-lab${q ?? ""}`)} />
        )}
        {page === "contacts" && (
          <Customer360Page onOpenCall={(id) => go(`calls/${id}`)} onOpenAiLab={(q) => go(`ai-lab${q ?? ""}`)} />
        )}
        {page === "managers" && <ManagersAnalyticsPage />}
        {page === "ai-lab" && <AiLabPage onOpenCall={(id) => go(`calls/${id}`)} />}
        {page === "connectors" && <ConnectorsPage />}
        {page === "users" && <UsersPage />}
        {page === "settings" && <SettingsPage />}
      </div>
      </div>
      {uploadOpen && (
        <UploadCallModal
          onClose={() => setUploadOpen(false)}
          onDone={(id) => { setUploadOpen(false); go(`calls/${id}`); }}
        />
      )}
    </div>
  );
}

export default function AppRoot() {
  return (
    <ToastProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </ToastProvider>
  );
}

import { ru, STATE_RU } from "./ru";

/** Обратная совместимость: бейдж статуса и формат длительности (используются
    компонентами ленты/борда/таймлайна). */
export function StateBadge({ state }: { state: string }) {
  const tone =
    state === "done" ? "success" : state === "failed" ? "danger" : "warning";
  const label = ru(STATE_RU, state, state);
  return <span className={`badge ${tone}`}>{label}</span>;
}

export function fmtDur(sec: number | null): string {
  if (!sec) return "—";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
