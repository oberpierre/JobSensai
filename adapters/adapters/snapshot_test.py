import json
import tempfile
import unittest
from pathlib import Path

from adapters.adapters.base import DiscoveryAdapter, ExtractionAdapter
from adapters.adapters.snapshot import DiscoverySnapshotTest, ExtractionSnapshotTest

_JOB_LINKS = ["https://example.com/a", "https://example.com/b"]
_NEXT_LINKS = ["https://example.com/jobs?page=2"]


class _MatchingAdapter(DiscoveryAdapter):
    domains = ["example.com"]

    def get_job_links(self, html: str, url: str) -> list[str]:
        return list(_JOB_LINKS) if "JOBS" in html else []

    def get_next_page_links(self, html: str, url: str) -> list[str]:
        return list(_NEXT_LINKS) if "JOBS" in html else []


class _MissingAdapter(DiscoveryAdapter):
    domains = ["example.com"]

    def get_job_links(self, html: str, url: str) -> list[str]:
        return []

    def get_next_page_links(self, html: str, url: str) -> list[str]:
        return []


class _OverSelectingAdapter(DiscoveryAdapter):
    domains = ["example.com"]

    def get_job_links(self, html: str, url: str) -> list[str]:
        extra = "https://example.com/not-a-job"
        return [*_JOB_LINKS, extra] if "JOBS" in html else []

    def get_next_page_links(self, html: str, url: str) -> list[str]:
        return list(_NEXT_LINKS) if "JOBS" in html else []


def _run(test_cls) -> unittest.TestResult:
    suite = unittest.TestLoader().loadTestsFromTestCase(test_cls)
    return suite.run(unittest.TestResult())


class TestDiscoverySnapshotTest(unittest.TestCase):
    def _snapshot_case(self, adapter_cls, fixtures: Path):
        fixtures.mkdir(parents=True)
        (fixtures / "index.html").write_text("<html>JOBS</html>")
        (fixtures / "expected.json").write_text(
            json.dumps(
                {
                    "url": "https://example.com/jobs",
                    "job_links": _JOB_LINKS,
                    "next_page_links": _NEXT_LINKS,
                }
            )
        )

        class _Case(DiscoverySnapshotTest, unittest.TestCase):
            def _fixtures_dir(self_inner) -> Path:
                return fixtures

        _Case.adapter_cls = adapter_cls
        return _Case

    def test_passes_when_adapter_reproduces_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = self._snapshot_case(_MatchingAdapter, Path(tmp) / "sample")
            result = _run(case)
        self.assertTrue(result.wasSuccessful(), result.failures)

    def test_fails_when_adapter_misses_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = self._snapshot_case(_MissingAdapter, Path(tmp) / "sample")
            result = _run(case)
        self.assertFalse(result.wasSuccessful())
        # Both the job-link and next-page assertions should fail.
        self.assertEqual(len(result.failures), 2)

    def test_fails_when_adapter_over_selects(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = self._snapshot_case(_OverSelectingAdapter, Path(tmp) / "sample")
            result = _run(case)
        self.assertFalse(result.wasSuccessful())
        # Exact-set equality catches the one extra (over-selected) job link.
        self.assertEqual(len(result.failures), 1)


_SILVER = {
    "url": "https://example.com/job/1",
    "title": "Staff Engineer",
    "company_name": "Acme",
    "employment_type": "Full-time",
    "locations": ["Remote", "NYC"],
    "categories": ["Engineering"],
    "description": "We build things.",
    "metadata": {},
}


class _MatchingExtraction(ExtractionAdapter):
    domains = ["example.com"]

    def extract(self, html: str, url: str) -> dict:
        return dict(_SILVER)


class _WrongTitleExtraction(ExtractionAdapter):
    domains = ["example.com"]

    def extract(self, html: str, url: str) -> dict:
        return {**_SILVER, "title": "Something Else"}


class TestExtractionSnapshotTest(unittest.TestCase):
    def _snapshot_case(self, adapter_cls, fixtures: Path):
        fixtures.mkdir(parents=True)
        (fixtures / "detail.html").write_text("<html><body>a job</body></html>")
        (fixtures / "expected.json").write_text(json.dumps(_SILVER))

        class _Case(ExtractionSnapshotTest, unittest.TestCase):
            def _fixtures_dir(self_inner) -> Path:
                return fixtures

        _Case.adapter_cls = adapter_cls
        return _Case

    def test_passes_when_adapter_reproduces_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(self._snapshot_case(_MatchingExtraction, Path(tmp) / "s"))
        self.assertTrue(result.wasSuccessful(), result.failures)

    def test_fails_on_wrong_scalar_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(self._snapshot_case(_WrongTitleExtraction, Path(tmp) / "s"))
        self.assertFalse(result.wasSuccessful())


if __name__ == "__main__":
    unittest.main()
