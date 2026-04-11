import unittest
import uuid
from datetime import datetime, UTC

from scraper.models import JobPosting


class TestModels(unittest.TestCase):
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
