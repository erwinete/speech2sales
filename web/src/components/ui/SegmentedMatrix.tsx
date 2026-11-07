// SegmentedMatrix (ТЗ v6.0 §3.3): лента стыкованных ячеек для выбора из 2-4
// режимов (режим выборки AI Lab, провайдер, сортировка).
import React from "react";

export const SegmentedMatrix: React.FC<{
  options: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
  ariaLabel?: string;
}> = ({ options, value, onChange, ariaLabel }) => {
  return (
    <div className="segmented-matrix" role="radiogroup" aria-label={ariaLabel}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          data-active={value === o.value ? "true" : "false"}
          className="segmented-matrix__cell"
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
};
