import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scraper.backfill_silver import (
    BackfillCounts,
    _candidate_query,
    find_candidate_urls,
    run_backfill,
)


class TestCandidateQuery(unittest.TestCase):
    """Checks the compiled SQL directly: JSONB columns elsewhere in the schema
    make sqlite unable to create these tables, so .all() cannot run here, but
    the query still compiles to inspectable text against an unbound session.
    """

    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        self.session = sessionmaker(bind=engine)()

    def test_excludes_rows_with_an_existing_silver_row(self):
        sql = str(_candidate_query(self.session))
        self.assertIn("job_postings.id IS NULL", sql)

    def test_excludes_soft_deleted_bronze_rows(self):
        sql = str(_candidate_query(self.session))
        self.assertIn("raw_job_postings.deleted_at IS NULL", sql)

    def test_left_outer_joins_on_url(self):
        sql = str(_candidate_query(self.session))
        self.assertIn(
            "LEFT OUTER JOIN job_postings ON raw_job_postings.url = job_postings.url",
            sql,
        )


class TestFindCandidateUrls(unittest.TestCase):
    @patch("scraper.backfill_silver._candidate_query")
    def test_returns_the_url_of_each_matched_row(self, mock_candidate_query):
        mock_candidate_query.return_value.all.return_value = [
            MagicMock(url="https://example.com/1"),
            MagicMock(url="https://example.com/2"),
        ]

        urls = find_candidate_urls(MagicMock())

        self.assertEqual(urls, ["https://example.com/1", "https://example.com/2"])


class TestRunBackfill(unittest.TestCase):
    def setUp(self):
        self.redis = MagicMock()
        self.registry = MagicMock()

    @patch("scraper.backfill_silver.find_candidate_urls")
    def test_enqueues_a_matched_row_with_an_adapter(self, mock_find):
        mock_find.return_value = ["https://example.com/1"]
        self.registry.get_extraction_adapter.return_value = MagicMock()

        counts = run_backfill(MagicMock(), self.redis, self.registry)

        self.redis.lpush.assert_called_once_with(
            "silver_generation_tasks", '{"url": "https://example.com/1"}'
        )
        self.assertEqual(
            counts, BackfillCounts(matched=1, skipped_no_adapter=0, enqueued=1)
        )

    @patch("scraper.backfill_silver.find_candidate_urls")
    def test_skips_a_row_whose_domain_has_no_adapter(self, mock_find):
        mock_find.return_value = ["https://unknown.com/1"]
        self.registry.get_extraction_adapter.return_value = None

        counts = run_backfill(MagicMock(), self.redis, self.registry)

        self.redis.lpush.assert_not_called()
        self.assertEqual(
            counts, BackfillCounts(matched=1, skipped_no_adapter=1, enqueued=0)
        )

    @patch("scraper.backfill_silver.find_candidate_urls")
    def test_dry_run_reports_the_count_without_enqueuing(self, mock_find):
        mock_find.return_value = ["https://example.com/1"]
        self.registry.get_extraction_adapter.return_value = MagicMock()

        counts = run_backfill(MagicMock(), self.redis, self.registry, dry_run=True)

        self.redis.lpush.assert_not_called()
        self.assertEqual(
            counts, BackfillCounts(matched=1, skipped_no_adapter=0, enqueued=1)
        )


if __name__ == "__main__":
    unittest.main()
