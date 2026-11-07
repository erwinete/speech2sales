// SlabButton (ТЗ v6.0 §3.1): прямоугольная плашка со скошенным правым нижним
// углом, боковой планкой при наведении и техническим индексом.
import React from "react";
import { BrutalistGlyph, type GlyphName } from "./BrutalistGlyph";

export type SlabVariant = "default" | "primary" | "critical" | "ghost";

interface SlabButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: SlabVariant;
  glyph?: GlyphName;
  indexTag?: string;
  active?: boolean;
  size?: "sm" | "md";
}

export const SlabButton: React.FC<SlabButtonProps> = ({
  variant = "default",
  glyph,
  indexTag,
  active = false,
  size = "md",
  children,
  className = "",
  ...rest
}) => {
  return (
    <button
      type="button"
      data-variant={variant}
      data-active={active ? "true" : "false"}
      data-size={size}
      className={`slab-btn ${className}`}
      {...rest}
    >
      <span className="slab-btn__edge" aria-hidden="true" />
      {glyph && <BrutalistGlyph name={glyph} size={size === "sm" ? 14 : 16} />}
      <span className="slab-btn__label">{children}</span>
      {indexTag && <span className="slab-btn__tag">{indexTag}</span>}
    </button>
  );
};
