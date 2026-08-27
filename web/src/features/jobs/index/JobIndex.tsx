import { MicroLabel } from "../../../components/MicroLabel";
import styles from "./JobIndex.module.scss";

// Reads no data yet: the index has nothing to show and says so plainly.
export function JobIndex() {
  return (
    <div className={styles.empty}>
      <MicroLabel>no postings</MicroLabel>
      <p className={styles.message}>Nothing indexed yet.</p>
    </div>
  );
}
