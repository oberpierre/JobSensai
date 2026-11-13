import type { Pay } from "../../../api/types";
import { MicroLabel } from "../../../components/MicroLabel";
import { formatPay } from "./formatPay";
import styles from "./JobDetail.module.scss";

export function PaySection({ pay }: { pay: Pay }) {
  return (
    <div className={styles.sidebarSection}>
      <MicroLabel>Pay</MicroLabel>
      <p className={styles.fieldValue}>{formatPay(pay)}</p>
    </div>
  );
}
