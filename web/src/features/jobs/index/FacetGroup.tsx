import { useState } from "react";
import { MicroLabel } from "../../../components/MicroLabel";
import { facetValueLabel } from "./facetLabels";
import type { FacetValue } from "../../../api/types";
import styles from "./FacetGroup.module.scss";

const INITIALLY_SHOWN = 4;

// One facet's checkbox list, shared by the desktop sidebar and the mobile sheet.
// The expander collapses again, because a facet holding 25 values otherwise costs
// a phone a screenful of scrolling to get past.
export function FacetGroup({
  label,
  values,
  selected,
  onToggle,
}: {
  label: string;
  values: FacetValue[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  // A facet no board reports yet is absent rather than empty, a heading over a
  // message about a field nobody has sent being a row spent on nothing.
  if (values.length === 0) {
    return null;
  }

  const shown = expanded ? values : values.slice(0, INITIALLY_SHOWN);
  const hidden = values.length - INITIALLY_SHOWN;

  return (
    <div className={styles.group}>
      <MicroLabel>{label}</MicroLabel>
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
        {hidden > 0 && (
          <button
            type="button"
            className={styles.more}
            aria-expanded={expanded}
            onClick={() => setExpanded((open) => !open)}
          >
            {expanded ? "− show fewer" : `+ ${hidden} more`}
          </button>
        )}
      </div>
    </div>
  );
}
