// StepSelect (ТЗ v6.0 §3.3): кастомный селектор с 1px-сеткой пунктов —
// без нативного выпадающего меню ОС.
import React from "react";
import { BrutalistGlyph, type GlyphName } from "./BrutalistGlyph";

export interface StepOption {
  value: string;
  label: string;
  glyph?: GlyphName;
}

export const StepSelect: React.FC<{
  value: string;
  options: StepOption[];
  onChange: (value: string) => void;
  ariaLabel?: string;
}> = ({ value, options, onChange, ariaLabel }) => {
  const [open, setOpen] = React.useState(false);
  const rootRef = React.useRef<HTMLDivElement>(null);
  const current = options.find((o) => o.value === value);

  React.useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="step-select" ref={rootRef}>
      <button
        type="button"
        className="step-select__trigger"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
          {current?.glyph && <BrutalistGlyph name={current.glyph} size={14} />}
          {current?.label ?? value}
        </span>
        <span className="step-select__index">{String(options.findIndex((o) => o.value === value) + 1).padStart(2, "0")}</span>
      </button>
      {open && (
        <div className="step-select__menu" role="listbox">
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              role="option"
              aria-selected={o.value === value}
              data-selected={o.value === value ? "true" : "false"}
              className="step-select__option"
              onClick={() => { onChange(o.value); setOpen(false); }}
            >
              {o.glyph && <BrutalistGlyph name={o.glyph} size={14} />}
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
