import unittest
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from scraper.models import (
    START_URL_TYPE_HTML_CRAWL,
    START_URL_TYPE_JSON_API,
    Base,
    StartUrl,
)
from scraper.spiders.base_spider import BaseJobSpider


# sqlite has no JSONB/UUID types, and Base.metadata.create_all() would fail
# against it otherwise. Rendering them as TEXT is safe because only row
# selection is under test here, not the columns' real types.
@compiles(JSONB, "sqlite")
@compiles(UUID, "sqlite")
def _render_as_text_on_sqlite(element, compiler, **kw):
    return "TEXT"


class _FixtureSpider(BaseJobSpider):
    """Minimal concrete spider so load_start_urls can be exercised."""

    name = "fixture"
    start_urls = ["https://example.com/literal-a", "https://example.com/literal-b"]

    def parse(self, response) -> Iterator:
        return iter(())

    def parse_job(self, response) -> Iterator:
        return iter(())


class TestLoadStartUrls(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)()

    def test_returns_only_html_crawl_rows_ordered_by_name(self):
        self.session.add_all(
            [
                StartUrl(
                    name="zeta",
                    url="https://zeta.example.com",
                    type=START_URL_TYPE_HTML_CRAWL,
                ),
                StartUrl(
                    name="alpha",
                    url="https://alpha.example.com",
                    type=START_URL_TYPE_HTML_CRAWL,
                ),
                StartUrl(
                    name="beta-api",
                    url="https://beta.example.com/api",
                    type=START_URL_TYPE_JSON_API,
                ),
            ]
        )
        self.session.commit()

        pairs = _FixtureSpider.load_start_urls(self.session)

        self.assertEqual(
            [url for _id, url in pairs],
            ["https://alpha.example.com", "https://zeta.example.com"],
        )

    def test_falls_back_to_class_literal_when_table_empty(self):
        pairs = _FixtureSpider.load_start_urls(self.session)

        self.assertEqual(
            pairs,
            [
                (None, "https://example.com/literal-a"),
                (None, "https://example.com/literal-b"),
            ],
        )

    def test_does_not_fall_back_when_table_holds_only_json_api_rows(self):
        self.session.add(
            StartUrl(
                name="only-api",
                url="https://api.example.com",
                type=START_URL_TYPE_JSON_API,
            )
        )
        self.session.commit()

        pairs = _FixtureSpider.load_start_urls(self.session)

        self.assertEqual(pairs, [])


if __name__ == "__main__":
    unittest.main()
