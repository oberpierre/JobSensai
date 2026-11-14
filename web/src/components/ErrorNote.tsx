import styles from "./ErrorNote.module.scss";

// The failure message shown in place beside the controls that produced it, as
// opposed to ./StateCard's ErrorState, which stands in for content that failed
// to load.
export function ErrorNote({ message }: { message: string }) {
  return <p className={styles.note}>{message}</p>;
}
