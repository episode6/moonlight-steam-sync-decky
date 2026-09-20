import type { CSSProperties, ReactNode } from "react";

import type { Tone } from "../lib/join";

/** The mockup's pill colours (Game Mode is always dark). */
const TONES: Record<Tone, { background: string; color: string }> = {
  stream: { background: "rgba(123,77,255,0.22)", color: "#c3b0ff" },
  ok: { background: "rgba(91,163,43,0.2)", color: "#9be36b" },
  warn: { background: "rgba(224,160,43,0.18)", color: "#f2c76b" },
  bad: { background: "rgba(217,75,75,0.18)", color: "#ff9a9a" },
  neutral: { background: "rgba(139,152,168,0.18)", color: "#b7c2cf" },
};

/** A badge or chip: "stream button", "fuzzy", "art refreshes on next sync", … */
export function Pill({ tone, children, style }: { tone: Tone; children: ReactNode; style?: CSSProperties }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "1px 8px",
        borderRadius: 10,
        fontSize: 10.5,
        fontWeight: 600,
        letterSpacing: "0.03em",
        textTransform: "uppercase",
        whiteSpace: "nowrap",
        ...TONES[tone],
        ...style,
      }}
    >
      {children}
    </span>
  );
}
