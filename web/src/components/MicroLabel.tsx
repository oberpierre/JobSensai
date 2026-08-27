import type { ReactNode } from "react";
import styles from "./MicroLabel.module.scss";

// The 10px mono uppercase label that sits above nearly every panel in the design.
export function MicroLabel({ children }: { children: ReactNode }) {
  return <span className={styles.label}>{children}</span>;
}
