import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


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

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    # Soft delete: if not seen for N runs, this gets set
    deleted_at = Column(DateTime, nullable=True)

    scraper_run = relationship("ScraperRun")

    def __repr__(self):
        return f"<RawJobPosting(id={self.id}, url='{self.url}')>"
