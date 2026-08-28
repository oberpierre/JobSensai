"""SQLAlchemy query builder for GET /api/jobs."""

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from scraper.models import JobPosting


def filtered_job_postings(
    db: Session, q: str | None, include_closed: bool
) -> list[JobPosting]:
    query = db.query(JobPosting)
    if not include_closed:
        query = query.filter(JobPosting.deleted_at.is_(None))
    if q:
        needle = q.lower()
        query = query.filter(
            or_(
                func.lower(JobPosting.title).contains(needle),
                func.lower(JobPosting.company_name).contains(needle),
            )
        )
    return query.all()
