"""Pydantic payload models for the jobs and boards HTTP API."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, field_validator

BoardType = Literal["html_crawl", "json_api"]


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


class JobDetail(BaseModel):
    id: UUID
    url: str
    title: str
    company_name: str
    employment_type: str | None
    locations: list[str]
    categories: list[str]
    metadata: dict
    description: str
    first_seen: datetime
    last_seen: datetime
    closed: bool


class JobListResponse(BaseModel):
    items: list[JobSummary]
    total: int
    page: int
    page_size: int
    company_count: int


class FacetValue(BaseModel):
    value: str
    count: int


class FacetsResponse(BaseModel):
    location: list[FacetValue]
    company: list[FacetValue]
    employment_type: list[FacetValue]


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


class BoardCreate(BaseModel):
    name: str
    url: str
    type: BoardType
    active: bool = True

    _validate_name = field_validator("name")(_not_blank)
    _validate_url = field_validator("url")(_not_blank)


class BoardUpdate(BaseModel):
    # Type is fixed at creation. It stays accepted here so a request trying to
    # change it can be rejected, rather than silently ignored as an extra field
    # and read back as a change that happened.
    name: str
    url: str
    active: bool
    type: BoardType | None = None

    _validate_name = field_validator("name")(_not_blank)
    _validate_url = field_validator("url")(_not_blank)


class Board(BaseModel):
    id: UUID
    name: str
    url: str
    type: BoardType
    active: bool
    posting_count: int | None
    health: None
    created_at: datetime
    updated_at: datetime


class BoardListResponse(BaseModel):
    items: list[Board]
