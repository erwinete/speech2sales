/** Экран 7: Настройки (ТЗ §5.4 п.8): конструктор рубрик, словарь, пайплайн,
    152-ФЗ эразура + журнал аудита. */
import React from "react";
import { api, type AuditLogRow, type LexiconEntryRow, type RubricRow, type RubricSpec } from "../api";
import { useToast } from "../context/app";
import { Badge, EmptyState, Skeleton, Tabs } from "../components/ui";

export default function SettingsPage() {
  const [tab, setTab] = React.useState("rubrics");
  return (
    <div>
      <Tabs
        tabs={[
          { key: "rubrics", label: "Чек-лист скоринга" },
          { key: "lexicon", label: "Словарь организации" },
          { key: "pipeline", label: "Пайплайн и ML" },
          { key: "compliance", label: "152-ФЗ и аудит" },
        ]}
        active={tab}
        onChange={setTab}
      />
      {tab === "rubrics" && <RubricsTab />}
      {tab === "lexicon" && <LexiconTab />}
      {tab === "pipeline" && <PipelineTab />}
      {tab === "compliance" && <ComplianceTab />}
    </div>
  );
}

function RubricsTab() {
  const { push } = useToast();
  const [rubrics, setRubrics] = React.useState<RubricRow[] | null>(null);
  const [spec, setSpec] = React.useState<RubricSpec | null>(null);
  const [rescoreDays, setRescoreDays] = React.useState<string>("");
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(() => {
    api.rubrics().then((r) => {
      setRubrics(r.items);
      const active = r.items.find((x) => x.is_active);
      if (active) setSpec(active.spec);
    }).catch((e) => push("error", String(e).slice(0, 120)));
  }, [push]);
  React.useEffect(load, [load]);

  const totalWeight = spec ? spec.items.reduce((a, it) => a + Number(it.weight || 0), 0) : 0;

  const save = async () => {
    if (!spec) return;
    setBusy(true);
    try {
      const r = await api.updateActiveRubric({
        name: spec.rubric_id,
        spec: { ...spec, version: (rubrics?.[0]?.version ?? 1) + 1 },
        rescore_days: rescoreDays ? Number(rescoreDays) : undefined,
      });
      push("success", `Сохранена версия ${r.version}; пересчитано звонков: ${r.rescored}`);
      load();
    } catch (e) {
      push("error", `Ошибка сохранения: ${String(e).slice(0, 160)}`);
    } finally {
      setBusy(false);
    }
  };

  if (!spec) return <div className="card"><Skeleton rows={5} /></div>;

  return (
    <div>
      <div className="card">
        <div className="card-title">
          <h3>Активная рубрика: {spec.rubric_id} · макс. {spec.max_score} баллов</h3>
          <Badge tone={totalWeight === 100 ? "success" : "danger"}>Сумма весов = {totalWeight}</Badge>
        </div>
        <table>
          <thead>
            <tr><th>ID</th><th>Критерий</th><th className="num">Вес</th><th>Тип правила</th><th>Параметры</th></tr>
          </thead>
          <tbody>
            {spec.items.map((it, idx) => (
              <tr key={idx} style={{ cursor: "default" }}>
                <td className="mono">{it.id}</td>
                <td>
                  <input value={it.title} style={{ width: 260 }}
                    onChange={(e) => setSpec({ ...spec, items: spec.items.map((x, i) => i === idx ? { ...x, title: e.target.value } : x) })} />
                </td>
                <td className="num">
                  <input type="number" value={it.weight} style={{ width: 70 }}
                    onChange={(e) => setSpec({ ...spec, items: spec.items.map((x, i) => i === idx ? { ...x, weight: Number(e.target.value) } : x) })} />
                </td>
                <td className="mono">{it.rule.kind}</td>
                <td className="muted">{JSON.stringify({ ...it.rule, kind: undefined })}</td>
                <td>
                  <button className="ghost danger" onClick={() => setSpec({ ...spec, items: spec.items.filter((_, i) => i !== idx) })}>✕</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button onClick={() => setSpec({
          ...spec,
          items: [...spec.items, { id: `new_${Date.now()}`, title: "Новый критерий", weight: 0, rule: { kind: "lexicon", lexicon: "greeting", scope: "first_60s" } }],
        })}>+ Добавить пункт</button>
      </div>
      <div className="filter-bar">
        <input placeholder="Пересчитать звонков за N дней (пусто — не пересчитывать)"
          value={rescoreDays} onChange={(e) => setRescoreDays(e.target.value)} style={{ width: 320 }} />
        <button className="primary" disabled={busy || totalWeight !== 100} onClick={() => void save()}>
          {busy ? "Сохранение…" : "Сохранить новую версию и пересчитать"}
        </button>
      </div>
    </div>
  );
}

function LexiconTab() {
  const { push } = useToast();
  const [rows, setRows] = React.useState<LexiconEntryRow[] | null>(null);
  const [term, setTerm] = React.useState("");
  const [aliases, setAliases] = React.useState("");
  const [category, setCategory] = React.useState("");

  const load = React.useCallback(() => {
    api.lexicon().then((r) => setRows(r.items)).catch(() => setRows([]));
  }, []);
  React.useEffect(load, [load]);

  const add = async () => {
    if (!term.trim()) return;
    try {
      await api.createLexicon({
        term: term.trim(),
        aliases: aliases.split(",").map((a) => a.trim()).filter(Boolean),
        category: category || null,
      });
      push("success", "Запись добавлена");
      setTerm(""); setAliases(""); setCategory("");
      load();
    } catch (e) {
      push("error", String(e).slice(0, 140));
    }
  };

  return (
    <div>
      <div className="filter-bar">
        <input placeholder="Канонический термин (например, Полилог)" value={term} onChange={(e) => setTerm(e.target.value)} style={{ width: 260 }} />
        <input placeholder="Алиасы через запятую (поли лог, палилог)" value={aliases} onChange={(e) => setAliases(e.target.value)} style={{ width: 320 }} />
        <input placeholder="Категория" value={category} onChange={(e) => setCategory(e.target.value)} style={{ width: 140 }} />
        <button className="primary" onClick={() => void add()}>+ Добавить</button>
      </div>
      {!rows ? <Skeleton rows={3} /> : rows.length === 0 ? (
        <EmptyState icon="settings" text="Словарь пуст — добавьте термины и алиасы для исправления ошибок ASR" />
      ) : (
        <table>
          <thead><tr><th>Термин</th><th>Алиасы</th><th>Категория</th><th>Статус</th><th></th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ cursor: "default" }}>
                <td><b>{r.term}</b></td>
                <td className="muted">{r.aliases.join(", ") || "—"}</td>
                <td>{r.category ?? "—"}</td>
                <td>{r.enabled ? <Badge tone="success">вкл</Badge> : <Badge tone="neutral">выкл</Badge>}</td>
                <td>
                  <button className="ghost danger" onClick={async () => {
                    await api.deleteLexicon(r.id);
                    push("success", "Запись удалена");
                    load();
                  }}>Удалить</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function PipelineTab() {
  const [data, setData] = React.useState<Record<string, unknown> | null>(null);
  React.useEffect(() => {
    api.orgSettings().then(setData).catch(() => setData({}));
  }, []);
  if (!data) return <div className="card"><Skeleton rows={4} /></div>;
  const pipeline = (data.pipeline ?? {}) as Record<string, unknown>;
  return (
    <div className="card">
      <div className="card-title"><h3>Текущая конфигурация пайплайна</h3></div>
      <table style={{ cursor: "default" }}>
        <tbody>
          {Object.entries(pipeline).map(([k, v]) => (
            <tr key={k} style={{ cursor: "default" }}>
              <td style={{ width: 260 }}><b>{k}</b></td>
              <td className="mono">{typeof v === "object" ? JSON.stringify(v) : String(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <small className="muted">Изменение ASR-бэкенда и диаризации — через переменные окружения (POLYLOG_ASR_BACKEND, POLYLOG_DIARIZATION, POLYLOG_VOICEPRINT) и перезапуск сервиса.</small>
    </div>
  );
}

function ComplianceTab() {
  const { push } = useToast();
  const [audit, setAudit] = React.useState<AuditLogRow[] | null>(null);
  const [phone, setPhone] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(() => {
    api.audit().then((r) => setAudit(r.items)).catch(() => setAudit([]));
  }, []);
  React.useEffect(load, [load]);

  const erase = async () => {
    if (!phone.trim() || !reason.trim()) {
      push("error", "Укажите телефон и причину удаления");
      return;
    }
    setBusy(true);
    try {
      const r = await api.eraseSubject({ phone: phone.trim(), reason: reason.trim() });
      push("success", `Удалено звонков: ${r.erased_calls}, аудио: ${r.erased_audio_files}. Акт №${r.audit_id}`);
      setPhone(""); setReason("");
      load();
    } catch (e) {
      push("error", `Ошибка эразуры: ${String(e).slice(0, 140)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="card">
        <div className="card-title"><h3>Право на забвение (ст. 21 152-ФЗ)</h3></div>
        <small className="section-hint">
          Каскадно удаляет аудиофайлы, транскрипты, возражения, векторы; обезличивает номера; пишет неизменяемую запись в аудит.
        </small>
        <div className="filter-bar">
          <input placeholder="Телефон субъекта (+7...)" value={phone} onChange={(e) => setPhone(e.target.value)} style={{ width: 220 }} />
          <input placeholder="Причина удаления" value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: 320 }} />
          <button className="danger" disabled={busy} onClick={() => void erase()}>
            {busy ? "Удаление…" : "Удалить данные субъекта"}
          </button>
        </div>
      </div>

      <h3>Журнал аудита</h3>
      {!audit ? <Skeleton rows={4} /> : audit.length === 0 ? (
        <EmptyState icon="settings" text="Записей аудита пока нет" />
      ) : (
        <table>
          <thead><tr><th>Когда</th><th>Действие</th><th>Объект</th><th>ID</th></tr></thead>
          <tbody>
            {audit.map((r) => (
              <tr key={r.id} style={{ cursor: "default" }}>
                <td className="mono">{new Date(r.created_at).toLocaleString("ru-RU")}</td>
                <td><Badge tone={r.action.includes("erase") ? "danger" : r.action.includes("delete") ? "warning" : "brand"}>{r.action}</Badge></td>
                <td>{r.resource_type}</td>
                <td className="mono">{r.resource_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
