import { FacetGroup } from "./FacetGroup";
import type { FacetsResponse } from "../../../api/types";
import type { JobFilters } from "./useJobFilters";
import styles from "./FilterSheet.module.scss";

// The mobile filter sheet, reached from the header's Filters button below the
// 768px breakpoint. Renders nothing while closed, so it never duplicates the
// sidebar's controls in the accessibility tree.
export function FilterSheet({
  open,
  onClose,
  facets,
  filters,
  onToggleFacet,
  onIncludeClosedChange,
  onClearAll,
  total,
}: {
  open: boolean;
  onClose: () => void;
  facets: FacetsResponse | undefined;
  filters: Pick<
    JobFilters,
    "locations" | "companies" | "employmentTypes" | "includeClosed"
  >;
  onToggleFacet: (
    key: "location" | "company" | "employment_type",
    value: string,
  ) => void;
  onIncludeClosedChange: (value: boolean) => void;
  onClearAll: () => void;
  total: number;
}) {
  if (!open) return null;

  return (
    <div className={styles.overlay} role="dialog" aria-label="Filters">
      <div className={styles.header}>
        <span className={styles.title}>Filters</span>
        <span className={styles.actions}>
          <button type="button" className={styles.clear} onClick={onClearAll}>
            Clear all
          </button>
          <button
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label="Close filters"
          >
            ×
          </button>
        </span>
      </div>
      <FacetGroup
        label="Location"
        values={facets?.location ?? []}
        selected={filters.locations}
        onToggle={(value) => onToggleFacet("location", value)}
      />
      <FacetGroup
        label="Company"
        values={facets?.company ?? []}
        selected={filters.companies}
        onToggle={(value) => onToggleFacet("company", value)}
      />
      <FacetGroup
        label="Employment type"
        values={facets?.employment_type ?? []}
        selected={filters.employmentTypes}
        onToggle={(value) => onToggleFacet("employment_type", value)}
        emptyMessage="No board reports this field yet."
      />
      <label className={styles.closedToggle}>
        <input
          type="checkbox"
          checked={filters.includeClosed}
          onChange={(event) => onIncludeClosedChange(event.target.checked)}
        />
        Include closed postings
      </label>
      <button type="button" className={styles.apply} onClick={onClose}>
        Show {total} {total === 1 ? "posting" : "postings"}
      </button>
    </div>
  );
}
