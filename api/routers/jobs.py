"""GET /api/jobs."""

import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.queries import paged_job_postings
from api.schemas import JobListResponse, JobSummary, as_utc
from scraper.database import get_db
from scraper.models import JobPosting

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# Underscores inside a word (node_modules) are left alone, whereas ones flanked by
# a non-word character or a string boundary are markdown emphasis and get stripped.
_MD_MARKUP_RE = re.compile(r"[#*`>]+|(?<!\w)_+|_+(?!\w)")
_WHITESPACE_RE = re.compile(r"\s+")

# The route accepts no sort or page-size parameter today, so every page is this size.
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
    result = paged_job_postings(
        db,
        q=search_text,
        include_closed=include_closed,
        page=page,
        page_size=_PAGE_SIZE,
    )

    return JobListResponse(
        items=[_to_summary(job) for job in result.items],
        total=result.total,
        page=page,
        page_size=_PAGE_SIZE,
        company_count=result.company_count,
    )
