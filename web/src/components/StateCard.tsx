import type { ReactNode } from "react";
import { MicroLabel } from "./MicroLabel";
import styles from "./StateCard.module.scss";

// The card shell both the index and the detail screen build their loading,
// empty, not-found and error states from, so it exists once rather than once
// per screen.
export function StateCard({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className ? `${styles.card} ${className}` : styles.card}>
      {children}
    </div>
  );
}

export function LoadingState() {
  return (
    <StateCard>
      <MicroLabel>loading</MicroLabel>
      <div className={styles.skeletonRow} />
      <div className={styles.skeletonRow} />
    </StateCard>
  );
}

export function ErrorState({
  message,
  endpoint,
  status,
  onRetry,
  detail,
}: {
  message: string;
  endpoint: string;
  status?: number;
  onRetry: () => void;
  detail?: string;
}) {
  return (
    <StateCard className={styles.error}>
      <span className={styles.errorLabel}>error</span>
      <p className={styles.message}>{message}</p>
      {detail && <p className={styles.errorDetail}>{detail}</p>}
      <div className={styles.errorActions}>
        <button type="button" onClick={onRetry}>
          Retry
        </button>
        <span className={styles.errorCode}>
          {endpoint} → {status ?? "error"}
        </span>
      </div>
    </StateCard>
  );
}
