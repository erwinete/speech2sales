/** Экран 2: разбор звонка (ТЗ §5.4 п.3): шапка с действиями (reprocess,
    артефакт), stage_error-баннер, двухколоночная компоновка. */
import React from "react";
import { api, type CallDetailRow } from "../api";
import { useToast } from "../context/app";
import { fmtDur, StateBadge } from "../App";
import { Badge, Skeleton } from "../components/ui";
import CallDetail from "../components/CallDetail";

export default function CallDetailPage({
  callId, onBack, onOpenCall, onOpenContact, onOpenAiLab,
}: {
  callId: string;
  onBack: () => void;
  onOpenCall: (id: string) => void;
  onOpenContact: () => void;
  onOpenAiLab?: (query: string) => void;
}) {
  const { push } = useToast();
  const [detail, setDetail] = React.useState<CallDetailRow | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(() => {
    setDetail(null);
    api.callDetail(callId).then(setDetail).catch((e) => setError(String(e)));
  }, [callId]);
  React.useEffect(load, [load]);

  // V5-03: сценарий тренажёра из звонка (JSON-файл на скачивание)
  const makeScenario = async () => {
    try {
      const scn = await api.scenarioFromCall(callId);
      const blob = new Blob([JSON.stringify(scn, null, 1)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${scn.scenario_id}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
      push("success", `Сценарий «${scn.title}» готов`);
    } catch (e) {
      push("error", `Сценарий: ${String(e).slice(0, 120)}`);
    }
  };

  // V5-05: отправка результата разбора в CRM (webhook/amoCRM)
  const sendToCrm = async () => {
    try {
      const res = await api.pushCrm(callId);
      push(res.errors.length ? "error" : "success",
        `CRM: отправлено ${res.sent} (${res.targets.join(", ") || "нет целей"})` +
        (res.errors.length ? ` — ${res.errors[0]}` : ""));
    } catch (e) {
      push("error", `CRM: ${String(e).slice(0, 120)}`);
    }
  };

  const reprocess = async () => {
    setBusy(true);
    try {
      await api.reprocess(callId);
      push("success", "Анализ перезапущен");
      load();
    } catch (e) {
      push("error", `Ошибка репроцесса: ${String(e).slice(0, 100)}`);
    } finally {
      setBusy(false);
    }
  };

  const exportArtifact = async () => {
    try {
      const artifact = await api.artifact(callId);
      const blob = new Blob([JSON.stringify(artifact, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `call-${callId}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      push("error", `Экспорт не удался: ${String(e).slice(0, 100)}`);
    }
  };

  if (error) {
    return (
      <div>
        <button onClick={onBack}>К списку</button>
        <p style={{ color: "crimson" }}>Не удалось загрузить звонок: {error}</p>
        <button onClick={load}>Повторить</button>
      </div>
    );
  }
  if (!detail) {
    return <div className="card"><Skeleton rows={8} /></div>;
  }

  const isStereo = (detail.channels_map ?? null) !== null;
  return (
    <div>
      <button onClick={onBack}>К списку</button>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap", margin: "8px 0" }}>
        <h2 style={{ margin: 0 }}>
          Звонок <span className="mono">{detail.phone_from ?? detail.phone_to}</span>
        </h2>
        <span className="muted">
          {new Date(detail.started_at).toLocaleString("ru-RU")} · {fmtDur(detail.duration_sec)}
        </span>
        <StateBadge state={detail.state} />
        <Badge tone={isStereo ? "brand" : "neutral"}>
          {isStereo ? "Стерео (каналы)" : "Моно (диаризация)"}
        </Badge>
        <Badge tone="neutral">{detail.asr_backend_id}</Badge>
        <div style={{ flex: 1 }} />
        <button disabled={busy} onClick={() => void reprocess()}>⟳ Перезапустить анализ</button>
        {/* DEF-07 (ТЗ v4.0): быстрый переход звонка в ИИ-Анализатор */}
        {onOpenAiLab && (
          <button onClick={() => onOpenAiLab(`?mode=transcripts_range&call_ids=${callId}&days=90`)}>
            Разобрать в ИИ (LLM / MCP)
          </button>
        )}
        <button onClick={() => void makeScenario()}>Создать сценарий тренажёра</button>
        <button onClick={() => void sendToCrm()}>Отправить в CRM</button>
        <button onClick={() => void exportArtifact()}>Экспорт JSON</button>
      </div>

      {detail.stage_error && (
        <div className="card" style={{ background: "var(--status-danger-bg)", borderColor: "var(--status-danger)" }}>
          <b>Ошибка обработки:</b> {detail.stage_error.stage} — {detail.stage_error.error}
          <button style={{ marginLeft: 12 }} disabled={busy} onClick={() => void reprocess()}>Повторить</button>
        </div>
      )}

      <CallDetail
        detail={detail}
        onBack={onBack}
        onOpen={onOpenCall}
        onOpenContact={onOpenContact}
      />
    </div>
  );
}
