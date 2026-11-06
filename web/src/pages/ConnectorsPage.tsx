/** Экран 5: Центр интеграций (ТЗ §5.4 п.6): активные коннекторы с Verify/Sync,
    каталог 8 типов + мастер настройки. */
import React from "react";
import {
  api, type ConnectorCatalogItem, type ConnectorRow,
} from "../api";
import { useToast } from "../context/app";
import { Badge, EmptyState, Modal, Skeleton } from "../components/ui";

export default function ConnectorsPage() {
  const { push } = useToast();
  const [rows, setRows] = React.useState<ConnectorRow[] | null>(null);
  const [catalog, setCatalog] = React.useState<ConnectorCatalogItem[] | null>(null);
  const [wizard, setWizard] = React.useState<ConnectorCatalogItem | null>(null);
  const [busyId, setBusyId] = React.useState<string | null>(null);

  const load = React.useCallback(() => {
    api.listConnectors().then((r) => setRows(r.items)).catch(() => setRows([]));
    api.connectorCatalog().then((r) => setCatalog(r.items)).catch(() => setCatalog([]));
  }, []);
  React.useEffect(load, [load]);

  const act = async (id: string, kind: "verify" | "sync") => {
    setBusyId(id);
    try {
      if (kind === "verify") {
        const r = await api.verifyConnector(id);
        push(r.ok ? "success" : "error", r.ok ? "Связь установлена" : `Проверка не прошла: ${JSON.stringify(r.details).slice(0, 120)}`);
      } else {
        const r = await api.syncConnector(id);
        push(r.errors.length ? "error" : "success",
          `Найдено ${r.discovered}, загружено ${r.created}, дублей ${r.skipped_duplicates}${r.errors.length ? `, ошибок ${r.errors.length}` : ""}`);
      }
      load();
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (id: string) => {
    await api.deleteConnector(id);
    push("success", "Коннектор удалён (существующие звонки отвязаны)");
    load();
  };

  return (
    <div>
      <h3>Подключённые интеграции</h3>
      {!rows ? <Skeleton rows={3} /> : rows.length === 0 ? (
        <EmptyState icon="plug" text="Интеграций пока нет — подключите АТС или CRM из каталога ниже" />
      ) : (
        rows.map((c) => (
          <div key={c.id} className="card">
            <div className="card-title">
              <div>
                <b>{c.display_name}</b> <Badge tone={c.status === "active" ? "success" : c.status === "error" ? "danger" : "warning"}>{c.status}</Badge>
                <div className="muted mono">{c.kind}</div>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button disabled={busyId === c.id} onClick={() => void act(c.id, "verify")}>Проверить связь</button>
                <button disabled={busyId === c.id} onClick={() => void act(c.id, "sync")}>Синхронизировать</button>
                <button className="danger" onClick={() => void remove(c.id)}>Удалить</button>
              </div>
            </div>
            <small className="muted">
              Загружено звонков: {c.calls_ingested_total} · последняя синхронизация: {c.last_poll_at ? new Date(c.last_poll_at).toLocaleString("ru-RU") : "—"}
              {c.last_error && <> · <span style={{ color: "var(--status-danger)" }}>ошибка: {c.last_error.slice(0, 120)}</span></>}
            </small>
            <div style={{ marginTop: 6 }}>
              <small>Webhook URL: <code className="mono">{c.webhook_url}</code></small>
            </div>
          </div>
        ))
      )}

      <h3 style={{ marginTop: 24 }}>Каталог коннекторов</h3>
      <small className="section-hint">Клик по карточке — мастер подключения.</small>
      {!catalog ? <Skeleton rows={2} /> : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
          {catalog.map((c) => (
            <div key={c.kind} className="card" style={{ cursor: "pointer", margin: 0 }} onClick={() => setWizard(c)}>
              <b>{c.title}</b>
              <div className="muted" style={{ fontSize: 12, margin: "4px 0" }}>{c.description}</div>
              <Badge tone={c.category === "crm" ? "violet" : "brand"}>{c.category}</Badge>
            </div>
          ))}
        </div>
      )}

      {wizard && (
        <ConnectorWizard
          catalog={wizard}
          onClose={() => setWizard(null)}
          onDone={() => { setWizard(null); load(); }}
        />
      )}
    </div>
  );
}

function ConnectorWizard({ catalog, onClose, onDone }: { catalog: ConnectorCatalogItem; onClose: () => void; onDone: () => void }) {
  const { push } = useToast();
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState(false);
  const [name, setName] = React.useState(catalog.title);

  const submit = async () => {
    setBusy(true);
    try {
      const config: Record<string, unknown> = {};
      const secrets: Record<string, unknown> = {};
      for (const f of catalog.fields) {
        const v = values[f.name] ?? "";
        if (f.secret) secrets[f.name] = v;
        else config[f.name] = v;
      }
      await api.createConnector({
        kind: catalog.kind, display_name: name, config, secrets,
      });
      push("success", "Коннектор сохранён — проверьте связь");
      onDone();
    } catch (e) {
      push("error", `Сохранение не удалось: ${String(e).slice(0, 140)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={`Подключение: ${catalog.title}`} onClose={onClose}>
      <div className="form-row">
        <label>Название подключения</label>
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      {catalog.fields.map((f) => (
        <div className="form-row" key={f.name}>
          <label>{f.label}{f.required && " *"}</label>
          <input
            type={f.type === "password" ? "password" : "text"}
            placeholder={f.placeholder}
            value={values[f.name] ?? ""}
            onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
          />
        </div>
      ))}
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
        <button onClick={onClose}>Отмена</button>
        <button className="primary" disabled={busy} onClick={() => void submit()}>
          {busy ? "Сохранение…" : "Сохранить"}
        </button>
      </div>
    </Modal>
  );
}
