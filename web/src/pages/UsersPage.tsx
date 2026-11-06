/** Экран 6: Пользователи, роли RBAC и голосовые отпечатки (ТЗ §5.4 п.7). */
import React from "react";
import { api, type UserProfile } from "../api";
import { useToast } from "../context/app";
import { Badge, EmptyState, Modal, Skeleton } from "../components/ui";

const ROLE_LABELS: Record<string, string> = {
  admin: "Админ", supervisor: "РОП", analyst: "Аналитик", agent: "Менеджер", dpo: "DPO",
};

export default function UsersPage() {
  const { push } = useToast();
  const [rows, setRows] = React.useState<UserProfile[] | null>(null);
  const [q, setQ] = React.useState("");
  const [wizard, setWizard] = React.useState<null | { user: UserProfile | null }>(null);
  const [voices, setVoices] = React.useState<{ items: { agent_key: string; samples: number; model_id: string; user: { display_name: string | null } | null }[] } | null>(null);

  const load = React.useCallback(() => {
    api.listUsers(q ? { q } : undefined).then((r) => setRows(r.items)).catch(() => setRows([]));
    api.voiceprints().then(setVoices).catch(() => setVoices({ items: [] }));
  }, [q]);
  React.useEffect(load, [load]);

  const deactivate = async (id: string) => {
    await api.deactivateUser(id);
    push("success", "Пользователь деактивирован");
    load();
  };

  return (
    <div>
      <div className="filter-bar">
        <input placeholder="Поиск по имени или email" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 280 }} />
        <button className="primary" onClick={() => setWizard({ user: null })}>+ Добавить пользователя</button>
      </div>

      {!rows ? <Skeleton rows={4} /> : rows.length === 0 ? (
        <EmptyState icon="users" text="Пользователей нет — добавьте первого сотрудника" />
      ) : (
        <table>
          <thead>
            <tr>
              <th>Сотрудник</th><th>Роль</th><th>Отдел</th><th>Внутренние номера</th>
              <th>Голос. отпечаток</th><th className="num">Звонков</th><th className="num">Средний балл</th><th>Статус</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((u) => (
              <tr key={u.id} style={{ cursor: "default" }}>
                <td><b>{u.display_name}</b><div className="muted mono" style={{ fontSize: 11 }}>{u.email}</div></td>
                <td><Badge tone={u.role === "admin" ? "violet" : "brand"}>{ROLE_LABELS[u.role] ?? u.role}</Badge></td>
                <td>{u.team_name ?? "—"}</td>
                <td className="mono">{(u.agent_ext_ids ?? []).join(", ") || "—"}</td>
                <td>{u.has_voiceprint ? <Badge tone="success">{u.voiceprint_samples} сэмплов</Badge> : <span className="muted">—</span>}</td>
                <td className="num">{u.calls_count ?? 0}</td>
                <td className="num">{u.avg_score ?? "—"}</td>
                <td>{u.is_active ? <Badge tone="success">активен</Badge> : <Badge tone="neutral">отключён</Badge>}</td>
                <td>
                  <button className="ghost" onClick={() => setWizard({ user: u })}>Изменить</button>
                  {u.is_active && <button className="ghost" style={{ color: "var(--status-danger)" }} onClick={() => void deactivate(u.id!)}>Отключить</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3 style={{ marginTop: 24 }}>База голосовых отпечатков</h3>
      <small className="section-hint">
        Биометрические шаблоны (wespeaker) накапливаются из стерео-записей; используются для распознавания роли менеджера в моно-записях.
      </small>
      {!voices ? <Skeleton rows={2} /> : voices.items.length === 0 ? (
        <EmptyState icon="users" text="Отпечатков ещё нет — появятся после первых стерео-звонков" />
      ) : (
        <table>
          <thead><tr><th>Внутренний номер</th><th>Сэмплов</th><th>Модель</th><th>Менеджер</th><th></th></tr></thead>
          <tbody>
            {voices.items.map((v) => (
              <tr key={v.agent_key} style={{ cursor: "default" }}>
                <td className="mono">{v.agent_key}</td>
                <td className="num">{v.samples}</td>
                <td className="mono">{v.model_id}</td>
                <td>{v.user?.display_name ?? "—"}</td>
                <td>
                  <button className="ghost danger" onClick={async () => {
                    await api.deleteVoiceprint(v.agent_key);
                    push("success", "Отпечаток сброшен");
                    load();
                  }}>Сбросить</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {wizard && (
        <UserWizard
          user={wizard.user}
          onClose={() => setWizard(null)}
          onDone={() => { setWizard(null); load(); }}
        />
      )}
    </div>
  );
}

function UserWizard({ user, onClose, onDone }: { user: UserProfile | null; onClose: () => void; onDone: () => void }) {
  const { push } = useToast();
  const [email, setEmail] = React.useState(user?.email ?? "");
  const [displayName, setDisplayName] = React.useState(user?.display_name ?? "");
  const [password, setPassword] = React.useState("");
  const [role, setRole] = React.useState(user?.role ?? "agent");
  const [team, setTeam] = React.useState(user?.team_name ?? "");
  const [exts, setExts] = React.useState((user?.agent_ext_ids ?? []).join(", "));
  const [busy, setBusy] = React.useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      const extList = exts.split(",").map((x) => x.trim()).filter(Boolean);
      if (user?.id) {
        await api.updateUser(user.id, {
          display_name: displayName, role, team_name: team,
          agent_ext_ids: extList, is_active: user.is_active,
          ...(password ? { password } : {}),
        });
        push("success", "Пользователь обновлён");
      } else {
        await api.createUser({
          email, display_name: displayName, password, role,
          team_name: team || undefined, agent_ext_ids: extList,
        });
        push("success", "Пользователь создан; звонки по внутренним номерам привязаны");
      }
      onDone();
    } catch (e) {
      push("error", `Ошибка: ${String(e).slice(0, 140)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={user ? `Изменить: ${user.email}` : "Новый пользователь"} onClose={onClose}>
      {!user && (
        <div className="form-row">
          <label>Email (логин)</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="manager@company.ru" />
        </div>
      )}
      <div className="form-row">
        <label>Отображаемое имя</label>
        <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
      </div>
      <div className="form-row">
        <label>{user ? "Новый пароль (пусто — не менять)" : "Пароль"}</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </div>
      <div className="form-row">
        <label>Роль в системе</label>
        <select value={role} onChange={(e) => setRole(e.target.value as typeof role)}>
          <option value="admin">Администратор</option>
          <option value="supervisor">РОП (Supervisor)</option>
          <option value="analyst">Аналитик</option>
          <option value="agent">Менеджер</option>
          <option value="dpo">DPO (офицер безопасности)</option>
        </select>
      </div>
      <div className="form-row">
        <label>Отдел / команда</label>
        <input value={team} onChange={(e) => setTeam(e.target.value)} />
      </div>
      <div className="form-row">
        <label>Внутренние номера АТС (через запятую)</label>
        <input value={exts} onChange={(e) => setExts(e.target.value)} placeholder="101, 102" />
      </div>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
        <button onClick={onClose}>Отмена</button>
        <button className="primary" disabled={busy} onClick={() => void submit()}>
          {busy ? "Сохранение…" : "Сохранить"}
        </button>
      </div>
    </Modal>
  );
}
