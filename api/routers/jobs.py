"""GET /api/jobs and GET /api/jobs/facets."""

import re
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.queries import facet_counts, paged_job_postings
from api.schemas import (
    FacetsResponse,
    FacetValue,
    JobListResponse,
    JobSummary,
    as_utc,
)
from scraper.database import get_db
from scraper.models import JobPosting

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# Underscores inside a word (node_modules) are left alone, whereas ones flanked by
# a non-word character or a string boundary are markdown emphasis and get stripped.
_MD_MARKUP_RE = re.compile(r"[#*`>]+|(?<!\w)_+|_+(?!\w)")
_WHITESPACE_RE = re.compile(r"\s+")

# The route accepts no page-size parameter, so every page is this size.
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
    # noqa: B008 below - Query() evaluates once and nothing here mutates the list.
    location: list[str] = Query(default=[]),  # noqa: B008
    company: list[str] = Query(default=[]),  # noqa: B008
    employment_type: list[str] = Query(default=[]),  # noqa: B008
    include_closed: bool = Query(default=False),
    sort: Literal["newest", "oldest"] = Query(default="newest"),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),  # noqa: B008 - FastAPI's own dependency-injection idiom
) -> JobListResponse:
    result = paged_job_postings(
        db,
        q=search_text,
        locations=location,
        companies=company,
        employment_types=employment_type,
        include_closed=include_closed,
        sort=sort,
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


@router.get("/facets", response_model=FacetsResponse)
def job_facets(
    search_text: str | None = Query(default=None, alias="q"),
    include_closed: bool = Query(default=False),
    db: Session = Depends(get_db),  # noqa: B008 - FastAPI's own dependency-injection idiom
) -> FacetsResponse:
    counts = facet_counts(db, q=search_text, include_closed=include_closed)
    return FacetsResponse(
        location=[FacetValue(value=v, count=c) for v, c in counts.location],
        company=[FacetValue(value=v, count=c) for v, c in counts.company],
        employment_type=[
            FacetValue(value=v, count=c) for v, c in counts.employment_type
        ],
    )
