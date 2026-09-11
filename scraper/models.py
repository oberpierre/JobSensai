import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()

START_URL_TYPE_HTML_CRAWL = "html_crawl"
START_URL_TYPE_API = "api"

# ingest_events.stage: which pipeline stage refused a posting.
INGEST_STAGE_INDEX = "index"
INGEST_STAGE_DETAIL = "detail"

# ingest_events.reason: the four refusals _process_mapped_row guards against.
INGEST_REASON_NO_RULE = "no_rule"
INGEST_REASON_UNPARSEABLE_CONTENT = "unparseable_content"
INGEST_REASON_RULE_RAISED = "rule_raised"
INGEST_REASON_INVALID_SHAPE = "invalid_shape"


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
    Bronze Layer: a job posting's raw fetched content and metadata, HTML or otherwise.
    """

    __tablename__ = "raw_job_postings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # URL is the natural key for deduplication
    url = Column(Text, unique=True, nullable=False, index=True)

    raw_content = Column(Text, nullable=False)
    # What raw_content holds: page HTML for a crawled posting, the posting's own
    # document for one reached by API.
    content_type = Column(Text, nullable=False, default="text/html")
    # The URL actually fetched, which for an API posting is the feed rather than
    # the posting's own url.
    source_url = Column(Text, nullable=False)

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


class IngestEvent(Base):
    """A posting the pipeline refused, recorded so the fact outlives the log line."""

    __tablename__ = "ingest_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    occurred_at = Column(DateTime, default=func.now(), nullable=False)
    domain = Column(Text, nullable=False, index=True)
    start_url_id = Column(
        UUID(as_uuid=True),
        ForeignKey("start_urls.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_url = Column(Text, nullable=False)
    posting_url = Column(Text, nullable=True)
    stage = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    detail = Column(Text, nullable=True)

    def __repr__(self):
        return (
            f"<IngestEvent(id={self.id}, stage='{self.stage}', reason='{self.reason}')>"
        )
