import { useSearchParams } from "react-router";
import type { SortOrder } from "../../../api/jobsApi";

export type FacetKey = "location" | "company" | "employment_type";

export interface JobFilters {
  q: string;
  page: number;
  includeClosed: boolean;
  sort: SortOrder;
  locations: string[];
  companies: string[];
  employmentTypes: string[];
}

// Centralises every filter the index reads and writes against the URL query string,
// which is what keeps a filtered view linkable and lets the search box, the facet
// sidebar and the mobile sheet agree on one source of truth.
export function useJobFilters() {
  const [searchParams, setSearchParams] = useSearchParams();

  const filters: JobFilters = {
    q: searchParams.get("q") ?? "",
    page: Number(searchParams.get("page") ?? "1"),
    includeClosed: searchParams.get("include_closed") === "true",
    sort: searchParams.get("sort") === "oldest" ? "oldest" : "newest",
    locations: searchParams.getAll("location"),
    companies: searchParams.getAll("company"),
    employmentTypes: searchParams.getAll("employment_type"),
  };

  function update(
    mutate: (next: URLSearchParams) => void,
    options?: { replace?: boolean },
  ) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      mutate(next);
      return next;
    }, options);
  }

  function setPage(page: number) {
    update((next) => {
      // The first page is the absence of the parameter, so one state has one URL.
      if (page > 1) next.set("page", String(page));
      else next.delete("page");
    });
  }

  function setQ(value: string, options?: { replace?: boolean }) {
    update((next) => {
      if (value) next.set("q", value);
      else next.delete("q");
      next.delete("page");
    }, options);
  }

  function setIncludeClosed(value: boolean) {
    update((next) => {
      if (value) next.set("include_closed", "true");
      else next.delete("include_closed");
      next.delete("page");
    });
  }

  function setSort(value: SortOrder) {
    update((next) => {
      if (value === "oldest") next.set("sort", "oldest");
      else next.delete("sort");
      next.delete("page");
    });
  }

  function toggleFacetValue(key: FacetKey, value: string) {
    update((next) => {
      const current = next.getAll(key);
      const alreadySelected = current.includes(value);
      next.delete(key);
      for (const existing of current) {
        if (existing !== value) next.append(key, existing);
      }
      if (!alreadySelected) next.append(key, value);
      next.delete("page");
    });
  }

  function clearFacets() {
    update((next) => {
      next.delete("location");
      next.delete("company");
      next.delete("employment_type");
      next.delete("include_closed");
      next.delete("page");
    });
  }

  const activeFacetCount =
    filters.locations.length +
    filters.companies.length +
    filters.employmentTypes.length +
    (filters.includeClosed ? 1 : 0);

  return {
    filters,
    setPage,
    setQ,
    setIncludeClosed,
    setSort,
    toggleFacetValue,
    clearFacets,
    activeFacetCount,
  };
}
