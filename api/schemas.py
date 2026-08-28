"""Pydantic payload models for the jobs HTTP API."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel


def as_utc(value: datetime) -> datetime:
    """The DB stores naive timestamps that are UTC by convention; the contract requires
    an explicit offset on the wire, so attach one rather than let it come back naive."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class JobSummary(BaseModel):
    id: UUID
    url: str
    title: str
    company_name: str
    employment_type: str | None
    locations: list[str]
    categories: list[str]
    metadata: dict
    snippet: str
    first_seen: datetime
    last_seen: datetime
    closed: bool


class JobListResponse(BaseModel):
    items: list[JobSummary]
    total: int
    page: int
    page_size: int
    company_count: int
