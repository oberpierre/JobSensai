import { Link, useLocation } from "react-router";
import { MicroLabel } from "../../components/MicroLabel";
import styles from "./NotFound.module.scss";

interface NotFoundState {
  from?: string;
}

// One action only: a live count on a second action would need this page to
// fetch in order to render itself, and "Back to Home" already reaches the
// index that count would search.
export function NotFound() {
  const location = useLocation();
  const from = (location.state as NotFoundState | null)?.from;

  return (
    <div className={styles.page}>
      <MicroLabel>404 · not found</MicroLabel>
      <h1 className={styles.title}>Nothing lives at this address</h1>
      <p className={styles.message}>
        Check the link, or start again from the index.
      </p>
      {from && (
        <div className={styles.from}>
          <MicroLabel>redirected from</MicroLabel>
          <span className={styles.fromPath}>{from}</span>
        </div>
      )}
      <Link to="/" className={styles.action}>
        Back to Home
      </Link>
    </div>
  );
}
