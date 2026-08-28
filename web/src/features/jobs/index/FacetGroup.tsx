import { useState } from "react";
import { MicroLabel } from "../../../components/MicroLabel";
import { facetValueLabel } from "./facetLabels";
import type { FacetValue } from "../../../api/types";
import styles from "./FacetGroup.module.scss";

const INITIALLY_SHOWN = 4;

// One facet's checkbox list, shared by the desktop sidebar and the mobile sheet:
// the first four values plus a "+ N more" expander, and a message in place of the
// list when the board has never reported the field.
export function FacetGroup({
  label,
  values,
  selected,
  onToggle,
  emptyMessage,
}: {
  label: string;
  values: FacetValue[];
  selected: string[];
  onToggle: (value: string) => void;
  emptyMessage?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? values : values.slice(0, INITIALLY_SHOWN);
  const remaining = values.length - shown.length;

  return (
    <div className={styles.group}>
      <MicroLabel>{label}</MicroLabel>
      {values.length === 0 && emptyMessage && (
        <p className={styles.emptyMessage}>{emptyMessage}</p>
      )}
      {values.length > 0 && (
        <div className={styles.options}>
          {shown.map((facet) => (
            <label key={facet.value} className={styles.option}>
              <input
                type="checkbox"
                checked={selected.includes(facet.value)}
                onChange={() => onToggle(facet.value)}
              />
              <span className={styles.optionValue}>
                {facetValueLabel(facet.value)}
              </span>
              <span className={styles.optionCount}>{facet.count}</span>
            </label>
          ))}
          {remaining > 0 && (
            <button
              type="button"
              className={styles.more}
              onClick={() => setExpanded(true)}
            >
              + {remaining} more
            </button>
          )}
        </div>
      )}
    </div>
  );
}
