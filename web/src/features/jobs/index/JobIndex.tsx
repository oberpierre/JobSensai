import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useLocation } from "react-router";
import { MicroLabel } from "../../../components/MicroLabel";
import {
  StateCard,
  LoadingState,
  ErrorState,
} from "../../../components/StateCard";
import { useJobsApi } from "../../../api/useJobsApi";
import { ApiError } from "../../../api/ApiError";
import type { SortOrder } from "../../../api/jobsApi";
import type { JobListResponse } from "../../../api/types";
import { relativeTime } from "./relativeTime";
import { useJobFilters } from "./useJobFilters";
import { FacetSidebar } from "./FacetSidebar";
import { FilterSheet } from "./FilterSheet";
import styles from "./JobIndex.module.scss";

const SEARCH_DEBOUNCE_MS = 300;

// total and page_size are already computed over the filtered set, so the last page
// with results is derivable from this response without a second request.
function lastPage(data: JobListResponse): number {
  return Math.max(1, Math.ceil(data.total / data.page_size));
}

// Lists postings from the API, filtered by search, the facet sidebar, the closed
// toggle and sort, and paged, with every filter held in the URL so a view is
// linkable and survives a reload.
export function JobIndex() {
  const api = useJobsApi();
  const location = useLocation();
  const {
    filters,
    setPage,
    pageSearch,
    setQ,
    setIncludeClosed,
    setSort,
    toggleFacetValue,
    clearFacets,
    activeFacetCount,
  } = useJobFilters();

  const [searchText, setSearchText] = useState(filters.q);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const [sheetOpen, setSheetOpen] = useState(false);

  // Keeps the controlled input in step with q from every source that can change
  // it besides typing: back/forward navigation, a reload, or a linked-to URL.
  const [syncedQ, setSyncedQ] = useState(filters.q);
  if (filters.q !== syncedQ) {
    setSyncedQ(filters.q);
    setSearchText(filters.q);
  }

  useEffect(() => {
    return () => clearTimeout(debounceTimer.current);
  }, []);

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: [
      "jobs",
      filters.q,
      filters.page,
      filters.includeClosed,
      filters.sort,
      filters.locations,
      filters.companies,
      filters.employmentTypes,
    ],
    queryFn: () =>
      api.listJobs({
        q: filters.q || undefined,
        page: filters.page,
        includeClosed: filters.includeClosed,
        sort: filters.sort,
        location: filters.locations,
        company: filters.companies,
        employmentType: filters.employmentTypes,
      }),
  });

  // Each facet's counts narrow by every other filter, including the other
  // facets, so the key carries them all and refetches when any of them changes.
  const { data: facets } = useQuery({
    queryKey: [
      "jobFacets",
      filters.q,
      filters.includeClosed,
      filters.locations,
      filters.companies,
      filters.employmentTypes,
    ],
    queryFn: () =>
      api.getFacets({
        q: filters.q || undefined,
        includeClosed: filters.includeClosed,
        location: filters.locations,
        company: filters.companies,
        employmentType: filters.employmentTypes,
      }),
  });

  function handleSearchChange(value: string) {
    setSearchText(value);
    clearTimeout(debounceTimer.current);
    // Starting or clearing a search is a state the reader may want to come back
    // to, whereas refining one is not, so only the first of a run gets a history
    // entry. Replacing every time would overwrite the unfiltered list a fresh tab
    // opened on, leaving the back button to exit the app.
    const startsOrClearsASearch = (filters.q !== "") !== (value !== "");
    debounceTimer.current = setTimeout(() => {
      setQ(value, { replace: !startsOrClearsASearch });
    }, SEARCH_DEBOUNCE_MS);
  }

  // Checked against data.page, which the redirect itself corrects, rather than
  // data.items.length, which a legitimately empty last page would still fail and
  // loop on.
  if (!isPending && !isError && data && data.page > lastPage(data)) {
    return (
      <Navigate
        to={{
          pathname: location.pathname,
          search: pageSearch(lastPage(data)),
        }}
        replace
      />
    );
  }

  const facetProps = {
    filters: {
      locations: filters.locations,
      companies: filters.companies,
      employmentTypes: filters.employmentTypes,
      includeClosed: filters.includeClosed,
    },
    onToggleFacet: toggleFacetValue,
    onIncludeClosedChange: setIncludeClosed,
  };

  return (
    <div className={styles.page}>
      <div className={styles.topRow}>
        <label className={styles.search}>
          <MicroLabel>Search</MicroLabel>
          <input
            type="text"
            placeholder="Title or company"
            value={searchText}
            onChange={(event) => handleSearchChange(event.target.value)}
          />
        </label>
        <button
          type="button"
          className={styles.filtersButton}
          onClick={() => setSheetOpen(true)}
        >
          Filters{activeFacetCount > 0 ? ` · ${activeFacetCount}` : ""}
        </button>
      </div>

      <div className={styles.layout}>
        <FacetSidebar facets={facets} {...facetProps} />

        <main className={styles.main}>
          {isPending && <LoadingState />}
          {isError && (
            <ErrorState
              message="Couldn't load postings"
              endpoint="GET /api/jobs"
              detail="The API didn't respond. Postings already in the database are unaffected."
              status={error instanceof ApiError ? error.status : undefined}
              onRetry={() => refetch()}
            />
          )}
          {!isPending && !isError && data && data.total === 0 && <EmptyState />}
          {!isPending && !isError && data && data.total > 0 && (
            <ResultsList
              data={data}
              sort={filters.sort}
              onSetSort={setSort}
              onSetPage={setPage}
            />
          )}
        </main>
      </div>

      <FilterSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        facets={facets}
        {...facetProps}
        onClearAll={clearFacets}
        total={data?.total ?? 0}
      />
    </div>
  );
}

function ResultsList({
  data,
  sort,
  onSetSort,
  onSetPage,
}: {
  data: JobListResponse;
  sort: SortOrder;
  onSetSort: (sort: SortOrder) => void;
  onSetPage: (page: number) => void;
}) {
  const firstShown = (data.page - 1) * data.page_size + 1;
  const lastShown = (data.page - 1) * data.page_size + data.items.length;

  return (
    <>
      <div className={styles.summary}>
        <span className={styles.counts}>
          <span className={styles.total}>
            {data.total} {data.total === 1 ? "posting" : "postings"}
          </span>
          <span className={styles.companyCount}>
            {data.company_count}{" "}
            {data.company_count === 1 ? "company" : "companies"}
          </span>
        </span>
        <label className={styles.sort}>
          <span className={styles.sortLabel}>sort:</span>
          <select
            aria-label="Sort order"
            value={sort}
            onChange={(event) => onSetSort(event.target.value as SortOrder)}
          >
            <option value="newest">newest first</option>
            <option value="oldest">oldest first</option>
          </select>
        </label>
      </div>
      <ul className={styles.list}>
        {data.items.map((job) => (
          <li
            key={job.id}
            className={job.closed ? styles.rowClosed : styles.row}
          >
            <Link to={`/jobs/${job.id}/`} className={styles.rowLink}>
              <div className={styles.rowMain}>
                <span className={styles.title}>{job.title}</span>
                <div className={styles.meta}>
                  <span>{job.company_name}</span>
                  <span className={styles.dot}>·</span>
                  <span>
                    {job.locations.join(" · ") || "Location not specified"}
                  </span>
                  {job.closed && (
                    <span className={styles.closedBadge}>closed</span>
                  )}
                </div>
                {!job.closed && job.snippet && (
                  <p className={styles.snippet}>{job.snippet}</p>
                )}
              </div>
              <div className={styles.rowSeen}>
                <span>first seen {relativeTime(job.first_seen)}</span>
                <span>{job.employment_type ?? "type not specified"}</span>
              </div>
            </Link>
          </li>
        ))}
      </ul>
      <div className={styles.pagination}>
        <span>
          showing {firstShown}–{lastShown} of {data.total}
        </span>
        <span className={styles.pageLinks}>
          <button
            type="button"
            disabled={data.page <= 1}
            onClick={() => onSetPage(data.page - 1)}
          >
            ← prev
          </button>
          <button
            type="button"
            disabled={data.page * data.page_size >= data.total}
            onClick={() => onSetPage(data.page + 1)}
          >
            next →
          </button>
        </span>
      </div>
    </>
  );
}

function EmptyState() {
  return (
    <StateCard>
      <MicroLabel>no postings</MicroLabel>
      <p className={styles.message}>Nothing matches these filters.</p>
    </StateCard>
  );
}
