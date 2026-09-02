import type { ReactNode } from "react";
import styles from "./MicroLabel.module.scss";

// The 10px mono uppercase label that sits above nearly every panel in the design.
// Faint everywhere except where the label is the loudest thing on the screen.
export function MicroLabel({
  children,
  tone = "faint",
}: {
  children: ReactNode;
  tone?: "faint" | "accent";
}) {
  return (
    <span
      className={
        tone === "accent" ? `${styles.label} ${styles.accent}` : styles.label
      }
    >
      {children}
    </span>
  );
}
