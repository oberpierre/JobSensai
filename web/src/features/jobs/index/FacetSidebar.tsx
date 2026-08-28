import { MicroLabel } from "../../../components/MicroLabel";
import { FacetGroup } from "./FacetGroup";
import type { FacetsResponse } from "../../../api/types";
import type { JobFilters } from "./useJobFilters";
import styles from "./FacetSidebar.module.scss";

// The desktop facet sidebar, hidden below the 768px breakpoint in favour of the
// Filters button and its sheet, which reuse the same FacetGroup content.
export function FacetSidebar({
  facets,
  filters,
  onToggleFacet,
  onIncludeClosedChange,
}: {
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
}) {
  return (
    <aside className={styles.sidebar}>
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
        emptyMessage="No board reports this field yet. Values appear here as soon as one does."
      />
      <div className={styles.reserved}>
        <MicroLabel>Mapped fields</MicroLabel>
        <p className={styles.reservedNote}>
          Reserved slot: curated metadata facets drop in here without moving
          anything above.
        </p>
      </div>
      <label className={styles.closedToggle}>
        <input
          type="checkbox"
          checked={filters.includeClosed}
          onChange={(event) => onIncludeClosedChange(event.target.checked)}
        />
        Include closed postings
      </label>
    </aside>
  );
}
