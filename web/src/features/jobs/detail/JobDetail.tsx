import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useJobsApi } from "../../../api/useJobsApi";
import { ApiError } from "../../../api/ApiError";
import type { JobDetail as JobDetailPayload } from "../../../api/types";
import { MicroLabel } from "../../../components/MicroLabel";
import { relativeTime } from "../index/relativeTime";
import { MetadataChip } from "./MetadataChip";
import { humanizeKey, metadataValueText } from "./humanizeKey";
import styles from "./JobDetail.module.scss";

// Back-to-top earns its place only after roughly one viewport of scroll.
function useScrolledPastOneViewport(): boolean {
  const [past, setPast] = useState(false);
  useEffect(() => {
    function onScroll() {
      setPast(window.scrollY > window.innerHeight);
    }
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return past;
}

export function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const api = useJobsApi();
  const scrolledPast = useScrolledPastOneViewport();

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ["job", id],
    queryFn: () => api.getJob(id as string),
    enabled: id !== undefined,
  });

  const notFound = isError && error instanceof ApiError && error.status === 404;

  return (
    <div className={styles.page}>
      <Link to="/" className={styles.back}>
        ← all postings
      </Link>

      {isPending && <LoadingState />}
      {isError && notFound && <NotFoundState />}
      {isError && !notFound && (
        <ErrorState
          status={error instanceof ApiError ? error.status : undefined}
          onRetry={() => refetch()}
        />
      )}
      {!isPending && !isError && data && (
        <Detail job={data} scrolledPast={scrolledPast} />
      )}
    </div>
  );
}

function Detail({
  job,
  scrolledPast,
}: {
  job: JobDetailPayload;
  scrolledPast: boolean;
}) {
  return (
    <div className={styles.layout}>
      <article className={styles.article}>
        <header className={styles.header}>
          <h1 className={styles.title}>{job.title}</h1>
          <div className={styles.metaLine}>
            <span className={styles.company}>{job.company_name}</span>
            <span className={styles.metaDot}>·</span>
            <span>
              {job.locations.length > 0
                ? job.locations.join(" · ")
                : "Location not specified"}
            </span>
          </div>
          <div className={styles.badges}>
            {job.employment_type ? (
              <span className={styles.employmentBadge}>
                {job.employment_type}
              </span>
            ) : (
              <span className={styles.unspecifiedBadge}>
                Employment type not specified
              </span>
            )}
            {job.closed && <span className={styles.closedBadge}>Closed</span>}
          </div>
        </header>

        <div className={styles.description}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {job.description}
          </ReactMarkdown>
        </div>
      </article>

      <aside className={styles.sidebar}>
        <SourceCard job={job} />

        <div className={styles.sidebarSection}>
          <MicroLabel>Categories</MicroLabel>
          {job.categories.length > 0 ? (
            <p className={styles.categories}>{job.categories.join(", ")}</p>
          ) : (
            <p className={styles.categoriesEmpty}>
              Not provided by this board.
            </p>
          )}
        </div>

        <AdditionalDetails metadata={job.metadata} />
      </aside>

      <MobileActionBar job={job} />
      {scrolledPast && <BackToTop />}
    </div>
  );
}

function SourceCard({ job }: { job: JobDetailPayload }) {
  return (
    <div className={styles.sourceCard}>
      <MicroLabel>Source</MicroLabel>
      <a
        href={job.url}
        target="_blank"
        rel="noreferrer"
        className={job.closed ? styles.sourceLinkClosed : styles.sourceLink}
      >
        {job.closed
          ? "Original posting (likely dead)"
          : "View original posting ↗"}
      </a>
      <div className={styles.seen}>
        <span>first seen {relativeTime(job.first_seen)}</span>
        <span>last seen {relativeTime(job.last_seen)}</span>
      </div>
    </div>
  );
}

// Renders whatever the adapter's metadata dict holds, keys humanised and every
// key on the same footing, since the interface never hard-codes a metadata key.
function AdditionalDetails({
  metadata,
}: {
  metadata: Record<string, unknown>;
}) {
  const entries = Object.entries(metadata);
  if (entries.length === 0) return null;
  return (
    <div className={styles.sidebarSection}>
      <MicroLabel>Additional details</MicroLabel>
      <div className={styles.metadataGrid}>
        {entries.map(([key, value]) => (
          <div key={key} className={styles.metadataRow}>
            <span className={styles.metadataKey}>{humanizeKey(key)}</span>
            <MetadataChip value={metadataValueText(value)} />
          </div>
        ))}
      </div>
    </div>
  );
}

function MobileActionBar({ job }: { job: JobDetailPayload }) {
  return (
    <a
      href={job.url}
      target="_blank"
      rel="noreferrer"
      className={job.closed ? styles.mobileBarClosed : styles.mobileBar}
    >
      {job.closed
        ? "Original posting (likely dead)"
        : "View original posting ↗"}
    </a>
  );
}

function BackToTop() {
  return (
    <button
      type="button"
      className={styles.backToTop}
      onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
    >
      ↑
    </button>
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

function NotFoundState() {
  return (
    <div className={styles.stateCard}>
      <MicroLabel>not found</MicroLabel>
      <p className={styles.message}>No posting with that id.</p>
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
      <p className={styles.message}>Couldn&apos;t load this posting</p>
      <div className={styles.errorActions}>
        <button type="button" onClick={onRetry}>
          Retry
        </button>
        <span className={styles.errorCode}>
          GET /api/jobs/:id → {status ?? "error"}
        </span>
      </div>
    </div>
  );
}
