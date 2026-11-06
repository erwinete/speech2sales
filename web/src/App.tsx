/** AppShell + модульный роутер (History API, ТЗ §5.1 офлайн-режим) +
    страницы приложения. */
import React from "react";
import { AuthProvider, ToastProvider, useAuth, useToast } from "./context/app";
import { api } from "./api";
import { Icon } from "./components/ui";
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

function navigate(path: string) {
  window.history.pushState({}, "", path.startsWith("/") ? path : `/${path}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function Sidebar({ route, callsCount }: { route: Route; callsCount: number | null }) {
  const { user } = useAuth();
  const item = (r: string, icon: string, label: string, count?: number | null) => (
    <a
      className={`nav-item ${route.path === r || (r === "dashboard" && route.path === "dashboard") ? "active" : ""}`}
      href={`/${r}`}
      onClick={(e) => { e.preventDefault(); navigate(r); }}
    >
      <Icon name={icon} /> {label}
      {count != null && <span className="count">{count}</span>}
    </a>
  );
  return (
    <aside className="sidebar">
      <div className="logo">Полилог <span className="badge brand">API</span></div>
      <div className="group-label">Аналитика</div>
      {item("dashboard", "dashboard", "Дашборд и звонки", callsCount)}
      {item("contacts", "contacts", "Клиенты 360°")}
      {item("managers", "coach", "Команда и коучинг")}
      {user?.role === "admin" || user?.role === "supervisor" || user?.role === "analyst" || user?.is_service ? (
        item("ai-lab", "sparkles", "ИИ-Анализатор")
      ) : null}
      {user?.role === "admin" || user?.role === "supervisor" || user?.role === "analyst" || user?.is_service ? (
        <>
          <div className="group-label">Интеграции и управление</div>
          {item("connectors", "plug", "Коннекторы")}
          {item("users", "users", "Пользователи")}
          {item("settings", "settings", "Настройки")}
        </>
      ) : null}
      <div style={{ marginTop: "auto", padding: "10px", borderTop: "1px solid var(--border-subtle)" }}>
        <div style={{ fontWeight: 600, fontSize: 13 }}>{user?.display_name ?? "…"}</div>
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

  return (
    <div className="app-shell">
      <Sidebar route={route} callsCount={callsCount} />
      <div className="main">
        <div className="topbar">
          <h2 style={{ margin: 0 }}>
            {page === "dashboard" && "Дашборд и звонки"}
            {page === "contacts" && "Клиенты 360°"}
            {page === "managers" && "Команда и коучинг"}
            {page === "ai-lab" && "ИИ-Анализатор (LLM & MCP)"}
            {page === "connectors" && "Коннекторы АТС и CRM"}
            {page === "users" && "Пользователи и роли"}
            {page === "settings" && "Настройки"}
            {page === "calls" && "Разбор звонка"}
          </h2>
          <div className="spacer" />
          <button className="primary" onClick={() => setUploadOpen(true)}>+ Загрузить звонок</button>
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
          <CallDetailPage callId={param} onBack={() => go("dashboard")} onOpenCall={(id) => go(`calls/${id}`)} onOpenContact={() => go("contacts")} />
        )}
        {page === "contacts" && (
          <Customer360Page onOpenCall={(id) => go(`calls/${id}`)} />
        )}
        {page === "managers" && <ManagersAnalyticsPage />}
        {page === "ai-lab" && <AiLabPage onOpenCall={(id) => go(`calls/${id}`)} />}
        {page === "connectors" && <ConnectorsPage />}
        {page === "users" && <UsersPage />}
        {page === "settings" && <SettingsPage />}
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
