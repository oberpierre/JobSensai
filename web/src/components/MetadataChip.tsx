import type { CSSProperties } from "react";
import styles from "./MetadataChip.module.scss";

// Fixed lightness and chroma, hue alone varying by level, so the chips read as
// one progression rather than a status rainbow. Computed here rather than in
// the stylesheet because the hue is chosen at render time and this codebase
// keeps every literal colour in one place, which is not this component.
function levelColor(hue: number) {
  return {
    text: `oklch(0.45 0.11 ${hue})`,
    bg: `oklch(0.95 0.03 ${hue})`,
    border: `oklch(0.86 0.05 ${hue})`,
  };
}

// The five experience-level values the Google adapter actually emits. Keyed by
// value rather than by key, so the same lookup renders any metadata value the
// map names and a neutral chip for anything it doesn't, which means no component
// branches on which key it is looking at.
const LEVEL_COLORS: Record<string, ReturnType<typeof levelColor>> = {
  "Intern & Apprentice": levelColor(145),
  Early: levelColor(195),
  Mid: levelColor(250),
  Advanced: levelColor(300),
  "Director+": levelColor(25),
};

export function MetadataChip({ value }: { value: string }) {
  const colors = LEVEL_COLORS[value];
  if (colors === undefined) {
    return <span className={styles.neutral}>{value}</span>;
  }
  return (
    <span
      className={styles.chip}
      style={
        {
          "--chip-text": colors.text,
          "--chip-bg": colors.bg,
          "--chip-border": colors.border,
        } as CSSProperties
      }
    >
      {value}
    </span>
  );
}
