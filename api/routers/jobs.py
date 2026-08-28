"""GET /api/jobs."""

import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.queries import filtered_job_postings
from api.schemas import JobListResponse, JobSummary, as_utc
from scraper.database import get_db
from scraper.models import JobPosting

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_MARKUP_RE = re.compile(r"[#*_`>]+")
_WHITESPACE_RE = re.compile(r"\s+")

# Not yet a query parameter: no sort or page-size control exists on the screen this
# slice builds, so both stay fixed rather than accepting a value nothing sends.
_PAGE_SIZE = 25


def _snippet(description: str, limit: int = 240) -> str:
    text = _MD_LINK_RE.sub(r"\1", description)
    text = _MD_MARKUP_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text[:limit]


def _to_summary(job: JobPosting) -> JobSummary:
    return JobSummary(
        id=job.id,
        url=job.url,
        title=job.title,
        company_name=job.company_name,
        employment_type=job.employment_type,
        locations=job.locations or [],
        categories=job.categories or [],
        metadata=job.metadata_ or {},
        snippet=_snippet(job.description or ""),
        first_seen=as_utc(job.created_at),
        last_seen=as_utc(job.updated_at),
        closed=job.deleted_at is not None,
    )


@router.get("", response_model=JobListResponse)
def list_jobs(
    # `q` is the wire name the contract fixes, whereas the Python parameter it binds
    # to is spelled out, since one letter reads as a typo rather than a search term.
    search_text: str | None = Query(default=None, alias="q"),
    include_closed: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),  # noqa: B008 - FastAPI's own dependency-injection idiom
) -> JobListResponse:
    jobs = filtered_job_postings(db, q=search_text, include_closed=include_closed)
    total = len(jobs)
    company_count = len({job.company_name for job in jobs})

    jobs.sort(key=lambda job: job.created_at, reverse=True)
    start = (page - 1) * _PAGE_SIZE
    page_items = jobs[start : start + _PAGE_SIZE]

    return JobListResponse(
        items=[_to_summary(job) for job in page_items],
        total=total,
        page=page,
        page_size=_PAGE_SIZE,
        company_count=company_count,
    )
