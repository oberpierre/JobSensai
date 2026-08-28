"""SQLAlchemy query builders for GET /api/jobs and GET /api/jobs/facets."""

import uuid
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import func, or_
from sqlalchemy.orm import Query, Session

from scraper.models import JobPosting

UNSPECIFIED_EMPLOYMENT_TYPE = "__unspecified__"

_ORDER_BY = {
    "newest": (JobPosting.created_at.desc(), JobPosting.id.desc()),
    "oldest": (JobPosting.created_at.asc(), JobPosting.id.asc()),
}


@dataclass
class JobPage:
    items: list[JobPosting]
    total: int
    company_count: int


@dataclass
class FacetCounts:
    location: list[tuple[str, int]] = field(default_factory=list)
    company: list[tuple[str, int]] = field(default_factory=list)
    employment_type: list[tuple[str, int]] = field(default_factory=list)


def _q_and_closed_filtered(db: Session, q: str | None, include_closed: bool) -> Query:
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


def _employment_type_filter(employment_types: list[str]):
    wanted = [v for v in employment_types if v != UNSPECIFIED_EMPLOYMENT_TYPE]
    conditions = []
    if wanted:
        conditions.append(JobPosting.employment_type.in_(wanted))
    if UNSPECIFIED_EMPLOYMENT_TYPE in employment_types:
        conditions.append(JobPosting.employment_type.is_(None))
    return or_(*conditions)


def _facet_filtered_query(
    db: Session,
    q: str | None,
    include_closed: bool,
    companies: list[str],
    employment_types: list[str],
) -> Query:
    """Narrows by every facet except location in SQL. Location is a JSON array
    column with no comparator portable across Postgres and the SQLite the tests
    run against, so its membership check happens in Python, in
    `_location_matching_ids`."""
    query = _q_and_closed_filtered(db, q, include_closed)
    if companies:
        query = query.filter(JobPosting.company_name.in_(companies))
    if employment_types:
        query = query.filter(_employment_type_filter(employment_types))
    return query


def _location_matching_ids(query: Query, locations: list[str]) -> set[uuid.UUID] | None:
    """None means no location was selected, so the caller skips narrowing by id.
    Otherwise every id whose locations intersect the wanted set."""
    if not locations:
        return None
    wanted = set(locations)
    return {job.id for job in query.all() if wanted & set(job.locations or [])}


def paged_job_postings(
    db: Session,
    q: str | None,
    locations: list[str],
    companies: list[str],
    employment_types: list[str],
    include_closed: bool,
    sort: Literal["newest", "oldest"],
    page: int,
    page_size: int,
) -> JobPage:
    """One page of postings, sorted, with the total and the distinct company count
    computed by the database over the whole filtered set. id breaks ties within a
    shared created_at, which is not otherwise a total order and would let one row
    span two pages while another falls on neither."""
    query = _facet_filtered_query(db, q, include_closed, companies, employment_types)
    matching_ids = _location_matching_ids(query, locations)
    if matching_ids is not None:
        query = query.filter(JobPosting.id.in_(matching_ids))

    total = query.count()
    company_count = query.with_entities(
        func.count(func.distinct(JobPosting.company_name))
    ).scalar()
    items = (
        query.order_by(*_ORDER_BY[sort])
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return JobPage(items=items, total=total, company_count=company_count)


def _sorted_counts(pairs: Iterable[tuple[str, int]]) -> list[tuple[str, int]]:
    return sorted(pairs, key=lambda pair: (-pair[1], pair[0]))


def _company_counts(query: Query) -> list[tuple[str, int]]:
    rows = (
        query.with_entities(JobPosting.company_name, func.count())
        .group_by(JobPosting.company_name)
        .all()
    )
    return _sorted_counts(rows)


def _employment_type_counts(query: Query) -> list[tuple[str, int]]:
    """Real values are one GROUP BY / COUNT. The unspecified bucket is a second
    COUNT rather than a member of that GROUP BY, since a board that has never
    reported the field would otherwise show a trivial "Unspecified: everything"
    facet, which teaches the reader nothing to filter."""
    real_rows = (
        query.filter(JobPosting.employment_type.isnot(None))
        .with_entities(JobPosting.employment_type, func.count())
        .group_by(JobPosting.employment_type)
        .all()
    )
    if not real_rows:
        return []
    unspecified_count = query.filter(JobPosting.employment_type.is_(None)).count()
    pairs = list(real_rows)
    if unspecified_count:
        pairs.append((UNSPECIFIED_EMPLOYMENT_TYPE, unspecified_count))
    return _sorted_counts(pairs)


def facet_counts(db: Session, q: str | None, include_closed: bool) -> FacetCounts:
    """Counts honour q and include_closed and ignore every facet selection, so a
    click never moves a number the sidebar is not currently narrowing by. Company
    and employment_type are a GROUP BY / COUNT in SQL, whereas location stays a
    Python pass over the locations column alone, since it is a JSON array with
    no membership comparator portable across Postgres and the SQLite the tests
    run against."""
    query = _q_and_closed_filtered(db, q, include_closed)

    location = Counter()
    for (locations,) in query.with_entities(JobPosting.locations).all():
        location.update(set(locations or []))

    return FacetCounts(
        location=_sorted_counts(location.items()),
        company=_company_counts(query),
        employment_type=_employment_type_counts(query),
    )
