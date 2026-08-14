#!/usr/bin/env python3
"""Enqueue Bronze postings for re-extraction once their adapter exists.

SilverWorker consumes silver_generation_tasks destructively, so a posting whose
adapter was missing or failing has no queued retry: the crawl interval or the
posting closing is the only other way it would be attempted again. Run this by
hand after an adapter merges.

Usage:
    bazel run //scraper:backfill_silver
    bazel run //scraper:backfill_silver -- --dry-run
"""

import argparse
import json
import os
from dataclasses import dataclass

import redis
from sqlalchemy.orm import Query, Session

from adapters.registry import AdapterRegistry
from scraper.database import SessionLocal
from scraper.models import JobPosting, RawJobPosting

QUEUE_NAME = "silver_generation_tasks"


@dataclass
class BackfillCounts:
    matched: int = 0
    skipped_no_adapter: int = 0
    enqueued: int = 0


def _candidate_query(db: Session) -> Query:
    """Bronze rows with no Silver row yet, excluding tombstoned ones.

    Neither worker persists a failed Silver attempt, so a missing join is the
    only signal available and a sufficient one: it means never attempted or
    previously failed, and both are backfill candidates. Split out from
    find_candidate_urls so a test can inspect the built query without a live
    database to execute .all() against.
    """
    return (
        db.query(RawJobPosting.url)
        .outerjoin(JobPosting, RawJobPosting.url == JobPosting.url)
        .filter(JobPosting.id.is_(None), RawJobPosting.deleted_at.is_(None))
    )


def find_candidate_urls(db: Session) -> list[str]:
    return [row.url for row in _candidate_query(db).all()]


def run_backfill(
    db: Session,
    redis_conn: redis.Redis,
    registry: AdapterRegistry,
    dry_run: bool = False,
) -> BackfillCounts:
    """Re-queue every candidate whose domain now has an extraction adapter.

    Reuses silver_generation_tasks rather than extracting inline, so there is
    one retry path through SilverWorker instead of two.
    """
    counts = BackfillCounts()
    for url in find_candidate_urls(db):
        counts.matched += 1
        if registry.get_extraction_adapter(url) is None:
            counts.skipped_no_adapter += 1
            continue
        counts.enqueued += 1
        if not dry_run:
            redis_conn.lpush(QUEUE_NAME, json.dumps({"url": url}))
    return counts


def _build_redis() -> redis.Redis:
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        username=os.getenv("REDIS_USERNAME") or None,
        password=os.getenv("REDIS_PASSWORD") or None,
        decode_responses=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enqueue Bronze postings missing a Silver row for re-extraction."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report matches without enqueuing anything.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        counts = run_backfill(
            db, _build_redis(), AdapterRegistry(), dry_run=args.dry_run
        )
    finally:
        db.close()

    print(
        f"matched={counts.matched} skipped_no_adapter={counts.skipped_no_adapter} "
        f"enqueued={counts.enqueued}"
    )


if __name__ == "__main__":
    main()
