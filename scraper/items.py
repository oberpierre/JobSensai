"""Scrapy item definitions for job postings."""

from scrapy import Field, Item


class RawJobItem(Item):
    """Item representing a raw job posting to be stored in Bronze layer."""

    # UUID will be generated on save
    id = Field()

    # Core fields
    url = Field()  # Unique identifier
    html_content = Field()

    # Which start_urls row the request that discovered this page came from
    start_url_id = Field()

    # Metadata stored as dict (will be JSONB in DB)
    metadata = Field()  # {job_board, scraper_version, page_title, etc}

    # Timestamps
    created_at = Field()
    updated_at = Field()
    deleted_at = Field()
