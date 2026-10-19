import { useEffect, useRef, useState } from "react";

// Визуальный плеер (doc 08): waveform-полоса + метки артефактов скоринга
// (возражения — красные, сигналы — зелёные, цитаты скоринга — синие).
// Клик в любую точку — перемотка.

export interface ArtifactMarker {
  startMs: number;
  kind: "objection" | "signal" | "score";
  label: string;
}

const MARKER_COLOR: Record<string, string> = {
  objection: "#d64545",
  signal: "#2e9e5b",
  score: "#3a6fd8",
};

export default function AudioTimeline({
  audioUrl,
  durationMs,
  markers,
  audioRef,
}: {
  audioUrl: string;
  durationMs: number;
  markers: ArtifactMarker[];
  audioRef: React.RefObject<HTMLAudioElement | null>;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [progress, setProgress] = useState(0); // 0..1
  const [playing, setPlaying] = useState(false);

  // waveform-пики из декодированного аудио
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch(audioUrl);
        const buf = await res.arrayBuffer();
        const ctx = new AudioContext();
        const audio = await ctx.decodeAudioData(buf);
        const data = audio.getChannelData(0);
        const bars = 140;
        const step = Math.floor(data.length / bars) || 1;
        const peaks: number[] = [];
        for (let i = 0; i < bars; i++) {
          let max = 0;
          for (let j = i * step; j < (i + 1) * step && j < data.length; j += 8) {
            const v = Math.abs(data[j]);
            if (v > max) max = v;
          }
          peaks.push(max);
        }
        void ctx.close();
        if (!alive) return;
        draw(peaks);
      } catch {
        if (alive) draw(null); // fallback: ровная полоса
      }
    })();

    function draw(peaks: number[] | null) {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const w = canvas.clientWidth, h = canvas.clientHeight;
      canvas.width = w * 2; canvas.height = h * 2; // retina
      const g = canvas.getContext("2d");
      if (!g) return;
      g.scale(2, 2);
      g.clearRect(0, 0, w, h);
      g.fillStyle = "#e3e8ef";
      const bars = peaks?.length ?? 100;
      for (let i = 0; i < bars; i++) {
        const v = peaks ? peaks[i] : 0.25;
        const bh = Math.max(2, v * (h - 8));
        g.fillRect((i / bars) * w, (h - bh) / 2, Math.max(1, w / bars - 1), bh);
      }
    }
    return () => { alive = false; };
  }, [audioUrl]);

  // прогресс-линия
  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const onTime = () => {
      const d = el.duration || durationMs / 1000;
      if (d) setProgress(Math.min(1, el.currentTime / d));
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    el.addEventListener("timeupdate", onTime);
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    return () => {
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
    };
  }, [audioRef, durationMs]);

  const seekTo = (frac: number) => {
    const el = audioRef.current;
    if (!el) return;
    const d = el.duration || durationMs / 1000;
    el.currentTime = frac * d;
  };

  const click = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    seekTo((e.clientX - rect.left) / rect.width);
  };

  const toggle = () => {
    const el = audioRef.current;
    if (!el) return;
    el.paused ? void el.play() : el.pause();
  };

  const mmss = (frac: number) => {
    const s = Math.floor(frac * (durationMs / 1000));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };

  return (
    <div style={{ margin: "12px 0", maxWidth: 760 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <button
          onClick={toggle}
          style={{
            width: 44, height: 44, borderRadius: "50%", border: "none", cursor: "pointer",
            background: "#2f6fed", color: "#fff", fontSize: 16,
          }}
        >
          {playing ? "❚❚" : "▶"}
        </button>
        <div
          ref={wrapRef}
          onClick={click}
          style={{ position: "relative", flexGrow: 1, height: 56, cursor: "pointer" }}
        >
          <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block" }} />
          {/* прогресс */}
          <div style={{
            position: "absolute", top: 0, bottom: 0, left: 0, width: `${progress * 100}%`,
            background: "#2f6fed14", borderRight: "2px solid #2f6fed", pointerEvents: "none",
          }} />
          {/* метки артефактов */}
          {markers.map((m, i) => {
            const frac = durationMs ? m.startMs / durationMs : 0;
            return (
              <div
                key={i}
                title={m.label}
                onClick={(e) => { e.stopPropagation(); seekTo(frac); }}
                style={{
                  position: "absolute", top: -6, left: `${frac * 100}%`,
                  width: 10, height: 10, borderRadius: "50%",
                  background: MARKER_COLOR[m.kind] ?? "#888",
                  border: "1px solid #fff", boxShadow: "0 0 2px #0004",
                  cursor: "pointer",
                }}
              />
            );
          })}
        </div>
        <span style={{ fontSize: 12, color: "#666", minWidth: 76, textAlign: "right" }}>
          {mmss(progress)} / {mmss(1)}
        </span>
      </div>
      <div style={{ display: "flex", gap: 14, marginTop: 4, fontSize: 12, color: "#666" }}>
        <Legend color={MARKER_COLOR.objection} label="возражение" />
        <Legend color={MARKER_COLOR.signal} label="сигнал" />
        <Legend color={MARKER_COLOR.score} label="цитата оценки" />
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />
      {label}
    </span>
  );
}
