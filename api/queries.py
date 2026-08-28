"""SQLAlchemy query builder for GET /api/jobs."""

from dataclasses import dataclass

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from scraper.models import JobPosting


@dataclass
class JobPage:
    items: list[JobPosting]
    total: int
    company_count: int


def _filtered_query(db: Session, q: str | None, include_closed: bool):
    query = db.query(JobPosting)
    if not include_closed:
        query = query.filter(JobPosting.deleted_at.is_(None))
    if q:
        needle = q.lower()
        # autoescape neutralises % and _ in the needle, which LIKE otherwise
        # treats as its own any-characters and single-character wildcards.
        query = query.filter(
            or_(
                func.lower(JobPosting.title).contains(needle, autoescape=True),
                func.lower(JobPosting.company_name).contains(needle, autoescape=True),
            )
        )
    return query


def paged_job_postings(
    db: Session,
    q: str | None,
    include_closed: bool,
    page: int,
    page_size: int,
) -> JobPage:
    """One page of postings, newest first, with the total and the distinct
    company count computed by the database over the whole filtered set."""
    query = _filtered_query(db, q, include_closed)
    total = query.count()
    company_count = query.with_entities(
        func.count(func.distinct(JobPosting.company_name))
    ).scalar()
    # id breaks ties within a shared created_at, which is not otherwise a total
    # order and would let one row span two pages while another falls on neither.
    items = (
        query.order_by(JobPosting.created_at.desc(), JobPosting.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return JobPage(items=items, total=total, company_count=company_count)
