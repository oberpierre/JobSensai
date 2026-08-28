import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { MicroLabel } from "../../../components/MicroLabel";
import { useJobsApi } from "../../../api/useJobsApi";
import { ApiError } from "../../../api/ApiError";
import type { JobListResponse } from "../../../api/types";
import { relativeTime } from "./relativeTime";
import styles from "./JobIndex.module.scss";

const SEARCH_DEBOUNCE_MS = 300;

// Lists postings from the API, filtered by search and the closed-postings toggle
// and paged, with every filter held in the URL so a view is linkable and survives
// a reload.
export function JobIndex() {
  const api = useJobsApi();
  const [searchParams, setSearchParams] = useSearchParams();
  const q = searchParams.get("q") ?? "";
  const page = Number(searchParams.get("page") ?? "1");
  const includeClosed = searchParams.get("include_closed") === "true";

  const [searchText, setSearchText] = useState(q);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );

  // Keeps the controlled input in step with q from every source that can change
  // it besides typing: back/forward navigation, a reload, or a linked-to URL.
  const [syncedQ, setSyncedQ] = useState(q);
  if (q !== syncedQ) {
    setSyncedQ(q);
    setSearchText(q);
  }

  useEffect(() => {
    return () => clearTimeout(debounceTimer.current);
  }, []);

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ["jobs", q, page, includeClosed],
    queryFn: () => api.listJobs({ q: q || undefined, page, includeClosed }),
  });

  function handleSearchChange(value: string) {
    setSearchText(value);
    clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value) {
            next.set("q", value);
          } else {
            next.delete("q");
          }
          next.delete("page");
          return next;
        },
        { replace: true },
      );
    }, SEARCH_DEBOUNCE_MS);
  }

  function handleIncludeClosedChange(value: boolean) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) {
        next.set("include_closed", "true");
      } else {
        next.delete("include_closed");
      }
      next.delete("page");
      return next;
    });
  }

  function setPage(nextPage: number) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("page", String(nextPage));
      return next;
    });
  }

  return (
    <div className={styles.page}>
      <div className={styles.controls}>
        <label className={styles.search}>
          <MicroLabel>Search</MicroLabel>
          <input
            type="text"
            placeholder="Title or company"
            value={searchText}
            onChange={(event) => handleSearchChange(event.target.value)}
          />
        </label>
        <label className={styles.closedToggle}>
          <input
            type="checkbox"
            checked={includeClosed}
            onChange={(event) =>
              handleIncludeClosedChange(event.target.checked)
            }
          />
          Include closed postings
        </label>
      </div>

      {isPending && <LoadingState />}
      {isError && (
        <ErrorState
          status={error instanceof ApiError ? error.status : undefined}
          onRetry={() => refetch()}
        />
      )}
      {!isPending && !isError && data && data.total === 0 && <EmptyState />}
      {!isPending && !isError && data && data.total > 0 && (
        <ResultsList data={data} onSetPage={setPage} />
      )}
    </div>
  );
}

function ResultsList({
  data,
  onSetPage,
}: {
  data: JobListResponse;
  onSetPage: (page: number) => void;
}) {
  const firstShown = (data.page - 1) * data.page_size + 1;
  const lastShown = (data.page - 1) * data.page_size + data.items.length;

  return (
    <>
      <div className={styles.summary}>
        <span className={styles.total}>
          {data.total} {data.total === 1 ? "posting" : "postings"}
        </span>
        <span className={styles.companyCount}>
          {data.company_count}{" "}
          {data.company_count === 1 ? "company" : "companies"}
        </span>
      </div>
      <ul className={styles.list}>
        {data.items.map((job) => (
          <li
            key={job.id}
            className={job.closed ? styles.rowClosed : styles.row}
          >
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

function LoadingState() {
  return (
    <div className={styles.stateCard}>
      <MicroLabel>loading</MicroLabel>
      <div className={styles.skeletonRow} />
      <div className={styles.skeletonRow} />
    </div>
  );
}

function EmptyState() {
  return (
    <div className={styles.stateCard}>
      <MicroLabel>no postings</MicroLabel>
      <p className={styles.message}>Nothing matches these filters.</p>
    </div>
  );
}

function ErrorState({
  status,
  onRetry,
}: {
  status?: number;
  onRetry: () => void;
}) {
  return (
    <div className={styles.errorCard}>
      <span className={styles.errorLabel}>error</span>
      <p className={styles.message}>Couldn&apos;t load postings</p>
      <p className={styles.errorDetail}>
        The API didn&apos;t respond. Postings already in the database are
        unaffected.
      </p>
      <div className={styles.errorActions}>
        <button type="button" onClick={onRetry}>
          Retry
        </button>
        <span className={styles.errorCode}>
          GET /api/jobs → {status ?? "error"}
        </span>
      </div>
    </div>
  );
}
