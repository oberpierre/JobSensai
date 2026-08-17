import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from scraper.backfill_silver import (
    BackfillCounts,
    find_candidate_urls,
    main,
    run_backfill,
)
from scraper.models import Base, JobPosting, RawJobPosting


# sqlite has no JSONB/UUID types, and Base.metadata.create_all() would fail
# against it otherwise. Rendering them as TEXT is safe because only row
# selection is under test here, not the columns' real types.
@compiles(JSONB, "sqlite")
@compiles(UUID, "sqlite")
def _render_as_text_on_sqlite(element, compiler, **kw):
    return "TEXT"


class TestCandidateQuery(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)()

    def test_matches_only_the_row_with_no_silver_counterpart_and_not_deleted(self):
        # Proves the AND, not merely that both filter fragments render
        # somewhere in the SQL.
        self.session.add_all(
            [
                RawJobPosting(
                    url="https://example.com/candidate", html_content="<html/>"
                ),
                RawJobPosting(
                    url="https://example.com/matched", html_content="<html/>"
                ),
                RawJobPosting(
                    url="https://example.com/deleted",
                    html_content="<html/>",
                    deleted_at=datetime.now(timezone.utc),
                ),
            ]
        )
        self.session.add(
            JobPosting(
                url="https://example.com/matched",
                title="Staff Engineer",
                company_name="Acme",
                description="We build things.",
            )
        )
        self.session.commit()

        self.assertEqual(
            find_candidate_urls(self.session), ["https://example.com/candidate"]
        )


class TestFindCandidateUrls(unittest.TestCase):
    # _candidate_query is split out so this test can substitute a fake query
    # and check the URL-extraction step on its own.
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
        self.registry.has_extraction_adapter.return_value = True

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
        self.registry.has_extraction_adapter.return_value = False

        counts = run_backfill(MagicMock(), self.redis, self.registry)

        self.redis.lpush.assert_not_called()
        self.assertEqual(
            counts, BackfillCounts(matched=1, skipped_no_adapter=1, enqueued=0)
        )

    @patch("scraper.backfill_silver.find_candidate_urls")
    def test_dry_run_reports_the_count_without_enqueuing(self, mock_find):
        mock_find.return_value = ["https://example.com/1"]
        self.registry.has_extraction_adapter.return_value = True

        counts = run_backfill(MagicMock(), self.redis, self.registry, dry_run=True)

        self.redis.lpush.assert_not_called()
        self.assertEqual(
            counts, BackfillCounts(matched=1, skipped_no_adapter=0, enqueued=1)
        )


class TestMainOutputFormat(unittest.TestCase):
    def _run_main(self, argv: list[str]) -> str:
        with (
            patch("scraper.backfill_silver.SessionLocal", return_value=MagicMock()),
            patch("scraper.backfill_silver._build_redis"),
            patch("scraper.backfill_silver.AdapterRegistry"),
            patch(
                "scraper.backfill_silver.run_backfill",
                return_value=BackfillCounts(
                    matched=1, skipped_no_adapter=0, enqueued=1
                ),
            ),
            patch("sys.argv", ["backfill_silver", *argv]),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                main()
        return buf.getvalue()

    def test_dry_run_output_carries_the_prefix_and_field_name(self):
        output = self._run_main(["--dry-run"])
        self.assertIn("[dry-run] ", output)
        self.assertIn("would_enqueue", output)

    def test_live_run_output_carries_neither(self):
        output = self._run_main([])
        self.assertNotIn("[dry-run] ", output)
        self.assertNotIn("would_enqueue", output)


if __name__ == "__main__":
    unittest.main()
