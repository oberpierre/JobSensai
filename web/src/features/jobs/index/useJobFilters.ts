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

// The API route rejects anything below 1, so a malformed `page` param (non-numeric,
// fractional, zero or negative) reads as page 1 rather than reaching the route and
// surfacing as an error card for what is really just a bad URL.
function parsePage(raw: string | null): number {
  const page = Number(raw ?? "1");
  return Number.isInteger(page) && page >= 1 ? page : 1;
}

// Centralises every filter the index reads and writes against the URL query string,
// which is what keeps a filtered view linkable and lets the search box, the facet
// sidebar and the mobile sheet agree on one source of truth.
export function useJobFilters() {
  const [searchParams, setSearchParams] = useSearchParams();

  const filters: JobFilters = {
    q: searchParams.get("q") ?? "",
    page: parsePage(searchParams.get("page")),
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

  // The first page is the absence of the parameter, so one state has one URL.
  // Shared by setPage and the past-the-end redirect, so neither can restate the rule.
  function pageSearch(page: number): string {
    const next = new URLSearchParams(searchParams);
    if (page > 1) next.set("page", String(page));
    else next.delete("page");
    return next.toString();
  }

  function setPage(page: number) {
    setSearchParams(pageSearch(page));
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
    pageSearch,
    setQ,
    setIncludeClosed,
    setSort,
    toggleFacetValue,
    clearFacets,
    activeFacetCount,
  };
}
