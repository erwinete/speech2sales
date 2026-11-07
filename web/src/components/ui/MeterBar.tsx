// MeterBar (ТЗ v6.0 §3.4): дискретная 10-сегментная шкала вместо цветных
// пилюль; числовое значение — tabular-nums.
import React from "react";

export type MeterTone = "positive" | "caution" | "critical" | "neutral";

export const MeterBar: React.FC<{
  value: number; // 0..1
  tone?: MeterTone;
  label?: string;
  format?: (v: number) => string;
}> = ({ value, tone = "neutral", label, format }) => {
  const clamped = Math.max(0, Math.min(1, value));
  const filled = Math.round(clamped * 10);
  const text = format ? format(clamped) : `${Math.round(clamped * 100)}%`;
  return (
    <span className="meter-bar" title={label}>
      <span className="meter-bar__track" aria-hidden="true">
        {Array.from({ length: 10 }).map((_, i) => (
          <span
            key={i}
            className="meter-bar__cell"
            data-filled={i < filled ? "true" : "false"}
            data-tone={tone}
          />
        ))}
      </span>
      <span className="meter-bar__value">{text}</span>
    </span>
  );
};
