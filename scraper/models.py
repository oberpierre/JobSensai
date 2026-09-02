import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()

START_URL_TYPE_HTML_CRAWL = "html_crawl"
START_URL_TYPE_JSON_API = "json_api"


class StartUrl(Base):
    """A crawl entry point an operator manages through the admin screen."""

    __tablename__ = "start_urls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, unique=True, nullable=False)
    url = Column(Text, unique=True, nullable=False, index=True)
    type = Column(Text, nullable=False, default=START_URL_TYPE_HTML_CRAWL)
    active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self):
        return f"<StartUrl(id={self.id}, name='{self.name}', url='{self.url}')>"


class ScraperRun(Base):
    """
    Tracks execution runs of a spider.
    Used for tombstoning logic: identifying items not seen in recent runs.
    """

    __tablename__ = "scraper_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    spider_name = Column(Text, nullable=False)
    started_at = Column(DateTime, default=func.now(), nullable=False)

    def __repr__(self):
        return (
            f"<ScraperRun(id={self.id}, spider='{self.spider_name}'"
            f", started='{self.started_at}')>"
        )


class RawJobPosting(Base):
    """
    Bronze Layer: Raw HTML and metadata of a job posting.
    """

    __tablename__ = "raw_job_postings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # URL is the natural key for deduplication
    url = Column(Text, unique=True, nullable=False, index=True)

    html_content = Column(Text, nullable=False)

    # Metadata stores flexible fields like job_board, page_title, scraper_version
    metadata_ = Column("metadata", JSONB, default=dict)

    # Tracking for Tombstoning
    last_seen_run_id = Column(
        UUID(as_uuid=True), ForeignKey("scraper_runs.id"), nullable=True, index=True
    )
    start_url_id = Column(
        UUID(as_uuid=True),
        ForeignKey("start_urls.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    # Soft delete: if not seen for N runs, this gets set
    deleted_at = Column(DateTime, nullable=True)

    scraper_run = relationship("ScraperRun")

    def __repr__(self):
        return f"<RawJobPosting(id={self.id}, url='{self.url}')>"


class JobPosting(Base):
    """
    Silver Layer: Structured job posting data.
    """

    __tablename__ = "job_postings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # URL is the natural key
    url = Column(Text, unique=True, nullable=False, index=True)

    title = Column(Text, nullable=False)
    company_name = Column(Text, nullable=False)
    employment_type = Column(Text, nullable=True)
    # Store arrays of strings as JSONB for Postgres array-like flexibility
    locations = Column(JSONB, default=list)
    categories = Column(JSONB, default=list)

    # description allows mapping multiple HTML fields and potentially map as markdown
    description = Column(Text, nullable=False)

    metadata_ = Column("metadata", JSONB, default=dict)

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<JobPosting(id={self.id}, url='{self.url}', title='{self.title}')>"
