// RailToggle (ТЗ v6.0 §3.2): механическая рельса с квадратным ползунком и
// текстом состояния ВКЛ/ВЫКЛ — вместо iOS-пилюль и голых чекбоксов.
import React from "react";
import { BrutalistGlyph, type GlyphName } from "./BrutalistGlyph";

interface RailToggleProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  description?: string;
  glyph?: GlyphName;
  disabled?: boolean;
  size?: "md" | "sm";
}

export const RailToggle: React.FC<RailToggleProps> = ({
  checked,
  onChange,
  label,
  description,
  glyph,
  disabled = false,
  size = "md",
}) => {
  return (
    <div
      className="rail-toggle"
      data-checked={checked ? "true" : "false"}
      data-disabled={disabled ? "true" : "false"}
      data-size={size}
      onClick={() => !disabled && onChange(!checked)}
      role="switch"
      aria-checked={checked}
      tabIndex={disabled ? -1 : 0}
      onKeyDown={(e) => {
        if (!disabled && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          onChange(!checked);
        }
      }}
    >
      <div className="rail-toggle__info">
        <div className="rail-toggle__title-row">
          {glyph && <BrutalistGlyph name={glyph} size={16} />}
          <span className="rail-toggle__label">{label}</span>
        </div>
        {description && <span className="rail-toggle__desc">{description}</span>}
      </div>
      <div className="rail-toggle__track" aria-hidden="true">
        <span className="rail-toggle__state-text">{checked ? "ВКЛ" : "ВЫКЛ"}</span>
        <span className="rail-toggle__thumb" />
      </div>
    </div>
  );
};
