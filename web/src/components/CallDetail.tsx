import { useRef, useState } from "react";
import { fmtDur, StateBadge } from "../App";
import { api, type CallDetailRow } from "../api";
import { OBJECTION_RU, RESPONSE_RU, ru } from "../ru";
import AudioTimeline, { type ArtifactMarker } from "./AudioTimeline";
import ContactRisk from "./ContactRisk";
import SimilarCalls from "./SimilarCalls";

// Экран звонка (doc 08 §4.3): визуальный плеер с метками артефактов +
// транскрипт с клик-перемоткой + карта оценки с цитатами + возражения.

export default function CallDetail({
  detail,
  onBack,
  onOpen,
  onOpenContact,
}: {
  detail: CallDetailRow;
  onBack: () => void;
  onOpen: (id: string) => void;
  onOpenContact?: (id: string) => void;
}) {
  const score = detail.scores.at(-1);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [activeSeg, setActiveSeg] = useState<number>(-1);
  const pendingSeekRef = useRef<number | null>(null);
  const [playerError, setPlayerError] = useState<string | null>(null);
  const [roleOverrides, setRoleOverrides] = useState<Record<number, string>>({});

  const flipRole = (idx: number): void => {
    const current = roleOverrides[idx] ?? detail.segments.find((s) => s.idx === idx)?.speaker;
    const next = current === "agent" ? "client" : "agent";
    setRoleOverrides((prev) => ({ ...prev, [idx]: next }));
    void fetch(`/api/v1/calls/${detail.id}/segments/${idx}/role`, {
      method: "POST",
      headers: {
        "X-Api-Key": localStorage.getItem("polylog_token") ?? "dev-insecure-token",
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({ speaker: next }),
    });
  };

  const durationMs = (detail.duration_sec ?? 0) * 1000;
  const markers: ArtifactMarker[] = [
    ...detail.objections.map((o) => ({
      startMs: o.start_ms ?? 0,
      kind: "objection" as const,
      label: `Возражение: ${ru(OBJECTION_RU, o.type)}`,
    })),
    ...(score?.items.flatMap((it) =>
      it.evidence
        .filter((ev) => ev.start_ms != null)
        .map((ev) => ({
          startMs: ev.start_ms as number,
          kind: "score" as const,
          label: `${it.title ?? it.item_id}: ${ev.span.slice(0, 60)}`,
        })),
    ) ?? []),
  ];

  const seek = (startMs: number) => {
    const el = audioRef.current;
    if (!el) return;
    setPlayerError(null);
    if (el.readyState >= 1) {
      // метаданные готовы — перематываем сразу
      el.currentTime = startMs / 1000;
      el.play().catch((e) => setPlayerError(`Плеер: ${String(e)}`));
    } else {
      // аудио ещё грузится: запомнить позицию и применить после загрузки
      pendingSeekRef.current = startMs;
      el.load();
      el.play().catch(() => { /* применится в onLoadedMetadata */ });
    }
    const idx = detail.segments.findIndex((s) => startMs >= s.start_ms && startMs < s.end_ms);
    if (idx !== -1) {
      setActiveSeg(idx);
      document.getElementById(`seg-${idx}`)?.scrollIntoView({ block: "nearest" });
    }
  };

  const onLoadedMetadata = () => {
    const el = audioRef.current;
    if (!el) return;
    if (pendingSeekRef.current != null) {
      el.currentTime = pendingSeekRef.current / 1000;
      pendingSeekRef.current = null;
      el.play().catch((e) => setPlayerError(`Плеер: ${String(e)}`));
    }
  };

  const onTimeUpdate = () => {
    const t = audioRef.current?.currentTime;
    if (t == null) return;
    const ms = t * 1000;
    const idx = detail.segments.findIndex((s) => ms >= s.start_ms && ms < s.end_ms);
    if (idx !== -1 && idx !== activeSeg) {
      setActiveSeg(idx);
      document.getElementById(`seg-${idx}`)?.scrollIntoView({ block: "nearest" });
    }
  };

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", maxWidth: 1100, margin: "0 auto", padding: 24 }}>
      <button onClick={onBack}>← К списку</button>
      <h2>
        Звонок {detail.phone_from ?? detail.phone_to}{" "}
        <small style={{ color: "#888", fontSize: 14 }}>
          {new Date(detail.started_at).toLocaleString("ru-RU")} · {fmtDur(detail.duration_sec)} ·{" "}
          <StateBadge state={detail.state} />
        </small>
      </h2>

      {playerError && <p style={{ color: "crimson", margin: "4px 0" }}>{playerError}</p>}
      <audio
        ref={audioRef}
        src={api.audioUrl(detail.id)}
        onTimeUpdate={onTimeUpdate}
        onLoadedMetadata={onLoadedMetadata}
        onError={() => setPlayerError("Не удалось загрузить запись — проверь, что API и Postgres запущены")}
        preload="auto"
      />
      <AudioTimeline
        audioUrl={api.audioUrl(detail.id)}
        durationMs={durationMs}
        markers={markers}
        audioRef={audioRef}
      />

      {score && (
        <section style={{ margin: "16px 0", padding: 16, border: "1px solid #ddd", borderRadius: 8 }}>
          <h3 style={{ margin: "0 0 8px" }}>
            Оценка звонка: <strong>{score.total}</strong> / 100{" "}
            <small style={{ color: "#888" }}>автоматическая оценка</small>
          </h3>
          {score.items.map((it) => (
            <details key={it.item_id} style={{ margin: "6px 0" }}>
              <summary style={{ cursor: "pointer" }}>
                <strong>{it.score}</strong>/{it.weight} — {it.title ?? it.item_id}
              </summary>
              <p style={{ color: "#555", margin: "4px 0" }}>{it.explanation}</p>
              {it.evidence.map((ev, i) => (
                <blockquote
                  key={i}
                  style={{ margin: "4px 0", padding: "6px 12px", background: "#f6f6f6", borderLeft: "3px solid #bbb" }}
                >
                  {ev.start_ms != null && (
                    <a
                      href="#audio"
                      onClick={(e) => {
                        e.preventDefault();
                        seek(ev.start_ms!);
                      }}
                      style={{ color: "#06c", marginRight: 6 }}
                    >
                      {fmtMs(ev.start_ms)}
                    </a>
                  )}
                  «{ev.span}»
                </blockquote>
              ))}
            </details>
          ))}
        </section>
      )}

      <ContactRisk call={detail} onOpenContact={onOpenContact} />
      <SimilarCalls call={detail} onOpen={onOpen} />

      {detail.objections.length > 0 && (
        <section style={{ margin: "16px 0" }}>
          <h3>Возражения ({detail.objections.length})</h3>
          {detail.objections.map((o, i) => (
            <div key={i} style={{ padding: "8px 0", borderBottom: "1px solid #eee" }}>
              <strong>{ru(OBJECTION_RU, o.type)}</strong> ·{" "}
              {ru(RESPONSE_RU, o.response_status, "не определено")}{" "}
              <small style={{ color: "#888" }}>уверенность {Math.round(o.confidence * 100)}%</small>
              <blockquote style={{ margin: "4px 0", color: "#444" }}>«{o.span_text}»</blockquote>
            </div>
          ))}
        </section>
      )}

      <section>
        <h3>
          Транскрипт ({detail.segments.length} реплик) — клик по реплике: слушать с этого места;
          «⟲» — исправить роль, если диаризация ошиблась (правка сохраняется)
        </h3>
        {detail.segments.map((s) => (
          <div
            key={s.idx}
            id={`seg-${s.idx}`}
            onClick={() => seek(s.start_ms)}
            style={{
              margin: "6px 0",
              padding: "4px 8px",
              borderRadius: 6,
              cursor: "pointer",
              background: s.idx === activeSeg ? "#fff3cd" : "transparent",
            }}
          >
            <small style={{ color: "#888" }}>
              {fmtMs(s.start_ms)}{" "}
              {(roleOverrides[s.idx] ?? s.speaker) === "agent"
                ? "🧑‍💼 менеджер"
                : (roleOverrides[s.idx] ?? s.speaker) === "client"
                  ? "👤 клиент"
                  : "🎙 разговор"}
              <a
                href="#role"
                onClick={(e) => {
                  e.stopPropagation();
                  void flipRole(s.idx);
                }}
                title="Исправить роль реплики (агент ⇄ клиент)"
                style={{ color: "#06c", marginLeft: 8, textDecoration: "none" }}
              >
                ⟲
              </a>
            </small>
            <div style={{ maxWidth: 720 }}>{s.text}</div>
          </div>
        ))}
      </section>
    </div>
  );
}

function fmtMs(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
