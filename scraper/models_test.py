import unittest
import uuid

from scraper.models import (
    START_URL_TYPE_HTML_CRAWL,
    START_URL_TYPE_JSON_API,
    JobPosting,
    RawJobPosting,
    StartUrl,
)


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


if __name__ == "__main__":
    unittest.main()
