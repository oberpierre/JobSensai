"""Scrapy item definitions for job postings."""

from scrapy import Field, Item


class RawJobItem(Item):
    """The JSON envelope a spider hands the Bronze worker, not the stored row."""

    # Core fields
    url = Field()  # Unique identifier
    html_content = Field()

    # Which start_urls row the request that discovered this page came from
    start_url_id = Field()

    # Metadata stored as dict (will be JSONB in DB)
    metadata = Field()  # {job_board, scraper_version, page_title, etc}
