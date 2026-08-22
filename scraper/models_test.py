import unittest
import uuid

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from scraper.models import (
    START_URL_TYPE_HTML_CRAWL,
    START_URL_TYPE_JSON_API,
    Base,
    JobPosting,
    RawJobPosting,
    StartUrl,
)


# sqlite has no JSONB/UUID types, and Base.metadata.create_all() would fail
# against it otherwise. Rendering them as TEXT is safe because only the
# ON DELETE SET NULL constraint is under test below, not the columns' real types.
@compiles(JSONB, "sqlite")
@compiles(UUID, "sqlite")
def _render_as_text_on_sqlite(element, compiler, **kw):
    return "TEXT"


class TestModels(unittest.TestCase):
    def test_start_url_creation(self):
        start_url = StartUrl(
            id=uuid.uuid4(),
            name="Google Careers",
            url="https://www.google.com/about/careers/applications/jobs/results/",
            type=START_URL_TYPE_HTML_CRAWL,
        )

        self.assertEqual(start_url.name, "Google Careers")
        self.assertEqual(start_url.type, START_URL_TYPE_HTML_CRAWL)

    def test_start_url_type_constants_are_distinct(self):
        self.assertNotEqual(START_URL_TYPE_HTML_CRAWL, START_URL_TYPE_JSON_API)

    def test_raw_job_posting_carries_its_start_url_id(self):
        start_url_id = uuid.uuid4()
        posting = RawJobPosting(
            id=uuid.uuid4(),
            url="https://example.com/job/1",
            html_content="<html/>",
            start_url_id=start_url_id,
        )

        self.assertEqual(posting.start_url_id, start_url_id)

    def test_job_posting_creation(self):
        job_posting = JobPosting(
            id=uuid.uuid4(),
            url="http://example.com/job/1",
            title="Software Engineer III, Generative AI",
            company_name="Google",
            employment_type="Full time",
            locations=["Remote", "Seattle, WA"],
            categories=["Engineering"],
            description="A great job.",
        )

        self.assertEqual(job_posting.title, "Software Engineer III, Generative AI")
        self.assertEqual(job_posting.company_name, "Google")
        self.assertEqual(job_posting.employment_type, "Full time")
        self.assertEqual(job_posting.locations, ["Remote", "Seattle, WA"])
        self.assertEqual(job_posting.categories, ["Engineering"])


class TestStartUrlDeletion(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")

        # sqlite only enforces foreign keys when told to per-connection; without
        # this the constraint below would pass for the wrong reason.
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, connection_record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)()

    def test_deleting_a_start_url_nulls_out_referencing_postings_instead_of_raising(
        self,
    ):
        start_url = StartUrl(
            name="Google Careers",
            url="https://www.google.com/about/careers/",
            type=START_URL_TYPE_HTML_CRAWL,
        )
        self.session.add(start_url)
        self.session.commit()

        posting = RawJobPosting(
            url="https://example.com/job/1",
            html_content="<html/>",
            start_url_id=start_url.id,
        )
        self.session.add(posting)
        self.session.commit()

        self.session.delete(start_url)
        self.session.commit()

        self.session.refresh(posting)
        self.assertIsNone(posting.start_url_id)


if __name__ == "__main__":
    unittest.main()
