// Файл: web/src/components/ui/BrutalistGlyph.tsx
// Единый рендер собственных сгенерированных изображений-глифов (ТЗ v6.0 §2.4).
import React from "react";

export type GlyphName =
  | "nav-dashboard"
  | "nav-calls"
  | "nav-risks"
  | "nav-objections"
  | "nav-reps"
  | "nav-customer"
  | "nav-llm"
  | "nav-settings"
  | "role-manager"
  | "role-client"
  | "sentiment-pos"
  | "sentiment-neu"
  | "sentiment-neg"
  | "status-alert"
  | "status-ok"
  | "status-pii"
  | "channel-call"
  | "channel-crm"
  | "channel-mail"
  | "channel-chat"
  | "channel-meet"
  | "ctrl-play"
  | "ctrl-pause"
  | "ctrl-upload"
  | "ctrl-copy"
  | "ctrl-sort-asc"
  | "ctrl-sort-desc"
  | "ctrl-theme";

interface BrutalistGlyphProps {
  name: GlyphName;
  size?: number;
  label?: string;
  className?: string;
}

export const BrutalistGlyph: React.FC<BrutalistGlyphProps> = ({
  name,
  size = 16,
  label,
  className = "",
}) => {
  return (
    <span
      className={`brutalist-glyph-frame ${className}`}
      style={{ width: size, height: size }}
      role={label ? "img" : "presentation"}
      aria-label={label}
    >
      <img
        src={`/assets/glyphs/${name}.png`}
        srcSet={`/assets/glyphs/${name}.png 2x, /assets/glyphs/${name}.svg 1x`}
        width={size}
        height={size}
        alt={label ?? ""}
        draggable={false}
        className="brutalist-glyph-img"
      />
    </span>
  );
};
