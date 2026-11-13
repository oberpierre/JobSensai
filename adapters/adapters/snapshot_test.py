import json
import tempfile
import unittest
from pathlib import Path

from adapters.adapters.base import DiscoveryAdapter, ExtractionAdapter
from adapters.adapters.snapshot import (
    DiscoverySnapshotTest,
    ExtractionSnapshotTest,
    metadata_violations,
)

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

    def test_guard_passes_when_snapshot_pins_a_job_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = self._snapshot_case(_MatchingAdapter, Path(tmp) / "sample")
            outcome = unittest.TestResult()
            case("test_snapshot_pins_at_least_one_job_link").run(outcome)
        self.assertTrue(outcome.wasSuccessful(), outcome.failures)

    def test_guard_fails_when_snapshot_pins_no_job_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = Path(tmp) / "s"
            fixtures.mkdir(parents=True)
            (fixtures / "index.html").write_text("<html></html>")
            (fixtures / "expected.json").write_text(
                json.dumps(
                    {
                        "url": "https://example.com/jobs",
                        "job_links": [],
                        "next_page_links": [],
                    }
                )
            )

            class _Case(DiscoverySnapshotTest, unittest.TestCase):
                def _fixtures_dir(self_inner) -> Path:
                    return fixtures

            _Case.adapter_cls = _MissingAdapter
            _Case.fixture_dir = "empty_discovery_fixture"
            outcome = unittest.TestResult()
            _Case("test_snapshot_pins_at_least_one_job_link").run(outcome)

        self.assertFalse(outcome.wasSuccessful())
        self.assertEqual(len(outcome.failures), 1)
        message = str(outcome.failures[0][1])
        self.assertIn("empty_discovery_fixture", message)
        self.assertIn("proves nothing", message)

    def test_guard_fails_with_a_message_when_job_links_key_is_absent(self):
        """A snapshot the orchestrator did not write may omit the key entirely,
        which must fail like an empty list rather than raise KeyError."""
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = Path(tmp) / "s"
            fixtures.mkdir(parents=True)
            (fixtures / "index.html").write_text("<html></html>")
            (fixtures / "expected.json").write_text(
                json.dumps({"url": "https://example.com/jobs"})
            )

            class _Case(DiscoverySnapshotTest, unittest.TestCase):
                def _fixtures_dir(self_inner) -> Path:
                    return fixtures

            _Case.adapter_cls = _MissingAdapter
            _Case.fixture_dir = "keyless_discovery_fixture"
            outcome = unittest.TestResult()
            _Case("test_snapshot_pins_at_least_one_job_link").run(outcome)

        self.assertFalse(outcome.wasSuccessful())
        self.assertEqual(outcome.errors, [])
        self.assertEqual(len(outcome.failures), 1)
        message = str(outcome.failures[0][1])
        self.assertIn("keyless_discovery_fixture", message)
        self.assertIn("proves nothing", message)

    def test_whole_suite_fails_rather_than_errors_when_job_links_key_is_absent(self):
        """The isolated-method run above never exercised the sibling method that
        reads the same missing key. Running the whole TestCase does."""
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = Path(tmp) / "s"
            fixtures.mkdir(parents=True)
            (fixtures / "index.html").write_text("<html></html>")
            (fixtures / "expected.json").write_text(
                json.dumps({"url": "https://example.com/jobs"})
            )

            class _Case(DiscoverySnapshotTest, unittest.TestCase):
                def _fixtures_dir(self_inner) -> Path:
                    return fixtures

            _Case.adapter_cls = _MissingAdapter
            _Case.fixture_dir = "keyless_discovery_fixture_whole_suite"
            result = _run(_Case)

        self.assertEqual(result.errors, [])
        self.assertFalse(result.wasSuccessful())


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


class _DropsMetadataExtraction(ExtractionAdapter):
    domains = ["example.com"]

    def extract(self, html: str, url: str) -> dict:
        return {k: v for k, v in _SILVER.items() if k != "metadata"}


class _DropsDescriptionExtraction(ExtractionAdapter):
    domains = ["example.com"]

    def extract(self, html: str, url: str) -> dict:
        return {k: v for k, v in _SILVER.items() if k != "description"}


class _WrongDescriptionExtraction(ExtractionAdapter):
    domains = ["example.com"]

    def extract(self, html: str, url: str) -> dict:
        return {**_SILVER, "description": "Completely unrelated content about nothing."}


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

    def test_fails_when_required_field_missing_though_snapshot_unpinned(self):
        """A non-nullable field missing from the output must fail even if unpinned.

        The value checks skip a field the truth agent could not ground, so without a
        presence check an adapter could ship a null-bound dict undetected.
        """
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = Path(tmp) / "s"
            fixtures.mkdir(parents=True)
            (fixtures / "detail.html").write_text("<html><body>a job</body></html>")
            unpinned = {k: v for k, v in _SILVER.items() if k != "description"}
            (fixtures / "expected.json").write_text(json.dumps(unpinned))

            class _Case(ExtractionSnapshotTest, unittest.TestCase):
                def _fixtures_dir(self_inner) -> Path:
                    return fixtures

            _Case.adapter_cls = _DropsDescriptionExtraction
            result = _run(_Case)

        self.assertFalse(result.wasSuccessful())
        self.assertTrue(
            any("required_field" in str(f[0]) for f in result.failures),
            result.failures,
        )

    def test_passes_when_optional_field_omitted(self):
        """A nullable/DB-defaulted field (metadata) may be omitted by the adapter."""
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(
                self._snapshot_case(_DropsMetadataExtraction, Path(tmp) / "s")
            )
        self.assertTrue(result.wasSuccessful(), result.failures)

    def test_fails_when_description_differs(self):
        """A description that isn't the pinned text fails the equality check."""
        with tempfile.TemporaryDirectory() as tmp:
            case = self._snapshot_case(_WrongDescriptionExtraction, Path(tmp) / "s")
            result = _run(case)
        self.assertFalse(result.wasSuccessful())
        self.assertTrue(
            any("description" in str(f[1]) for f in result.failures),
            result.failures,
        )

    def test_guard_passes_when_snapshot_pins_title_and_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = self._snapshot_case(_MatchingExtraction, Path(tmp) / "s")
            outcome = unittest.TestResult()
            case("test_snapshot_pins_a_title_and_a_description").run(outcome)
        self.assertTrue(outcome.wasSuccessful(), outcome.failures)

    def test_guard_fails_when_snapshot_pins_no_title_or_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = Path(tmp) / "s"
            fixtures.mkdir(parents=True)
            (fixtures / "detail.html").write_text("<html><body>a job</body></html>")
            blank = {**_SILVER, "title": "", "description": "   "}
            (fixtures / "expected.json").write_text(json.dumps(blank))

            class _Case(ExtractionSnapshotTest, unittest.TestCase):
                def _fixtures_dir(self_inner) -> Path:
                    return fixtures

            _Case.adapter_cls = _MatchingExtraction
            _Case.fixture_dir = "empty_extraction_fixture"
            outcome = unittest.TestResult()
            _Case("test_snapshot_pins_a_title_and_a_description").run(outcome)

        self.assertFalse(outcome.wasSuccessful())
        self.assertEqual(len(outcome.failures), 1)
        message = str(outcome.failures[0][1])
        self.assertIn("empty_extraction_fixture", message)
        self.assertIn("proves nothing", message)

    def test_guard_fails_with_a_message_when_title_is_not_a_string(self):
        """A snapshot the orchestrator did not write may pin a non-string title,
        which must fail like a blank one rather than raise AttributeError."""
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = Path(tmp) / "s"
            fixtures.mkdir(parents=True)
            (fixtures / "detail.html").write_text("<html><body>a job</body></html>")
            malformed = {**_SILVER, "title": 12345}
            (fixtures / "expected.json").write_text(json.dumps(malformed))

            class _Case(ExtractionSnapshotTest, unittest.TestCase):
                def _fixtures_dir(self_inner) -> Path:
                    return fixtures

            _Case.adapter_cls = _MatchingExtraction
            _Case.fixture_dir = "non_string_title_fixture"
            outcome = unittest.TestResult()
            _Case("test_snapshot_pins_a_title_and_a_description").run(outcome)

        self.assertFalse(outcome.wasSuccessful())
        self.assertEqual(outcome.errors, [])
        self.assertEqual(len(outcome.failures), 1)
        message = str(outcome.failures[0][1])
        self.assertIn("non_string_title_fixture", message)
        self.assertIn("proves nothing", message)

    def test_whole_suite_fails_rather_than_errors_when_description_is_null(self):
        """The isolated-method run above never exercised the sibling method that
        also calls .strip() on the same field. Running the whole TestCase does."""
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = Path(tmp) / "s"
            fixtures.mkdir(parents=True)
            (fixtures / "detail.html").write_text("<html><body>a job</body></html>")
            malformed = {**_SILVER, "description": None}
            (fixtures / "expected.json").write_text(json.dumps(malformed))

            class _Case(ExtractionSnapshotTest, unittest.TestCase):
                def _fixtures_dir(self_inner) -> Path:
                    return fixtures

            _Case.adapter_cls = _MatchingExtraction
            _Case.fixture_dir = "null_description_fixture_whole_suite"
            result = _run(_Case)

        self.assertEqual(result.errors, [])
        self.assertFalse(result.wasSuccessful())

    def test_metadata_conforms_fails_an_adapter_reporting_a_url(self):
        class _UrlMetadataExtraction(ExtractionAdapter):
            domains = ["example.com"]

            def extract(self, html: str, url: str) -> dict:
                return {**_SILVER, "metadata": {"apply": "https://example.com/apply"}}

        with tempfile.TemporaryDirectory() as tmp:
            case = self._snapshot_case(_UrlMetadataExtraction, Path(tmp) / "s")
            result = _run(case)

        failed = [f for f in result.failures if "test_metadata_conforms" in str(f[0])]
        self.assertEqual(len(failed), 1, result.failures)
        self.assertIn("holds a URL", str(failed[0][1]))


_NOT_VALUE = "is not a string, a number or a list of them"


class TestMetadataViolations(unittest.TestCase):
    def test_no_metadata_has_no_violations(self):
        self.assertEqual(metadata_violations({"categories": ["Engineering"]}), [])

    def test_strings_numbers_and_lists_of_them_conform(self):
        metadata = {"experience_level": "Mid", "openings": 0, "levels": ["Mid", 2]}
        data = {"metadata": metadata}
        self.assertEqual(metadata_violations(data), [])

    def test_metadata_that_is_not_an_object(self):
        self.assertEqual(
            metadata_violations({"metadata": ["Mid"]}),
            ["metadata is not an object"],
        )

    def test_key_with_a_space_and_capitals(self):
        self.assertEqual(
            metadata_violations({"metadata": {"Experience Level": "Mid"}}),
            ["metadata key 'Experience Level' is not lower snake_case"],
        )

    def test_camel_case_key(self):
        self.assertEqual(
            metadata_violations({"metadata": {"experienceLevel": "Mid"}}),
            ["metadata key 'experienceLevel' is not lower snake_case"],
        )

    def test_url_after_whitespace_and_in_capitals(self):
        data = {"metadata": {"apply": " HTTPS://example.com/apply"}}
        self.assertEqual(metadata_violations(data), ["metadata['apply'] holds a URL"])

    def test_url_nested_in_an_object_inside_a_list(self):
        data = {"metadata": {"links": [{"href": "http://x.example"}]}}
        self.assertEqual(
            metadata_violations(data),
            ["metadata['links'] holds a URL", f"metadata['links'] {_NOT_VALUE}"],
        )

    def test_url_inside_prose_is_not_a_url_value(self):
        data = {"metadata": {"note": "see https://x.example"}}
        self.assertEqual(metadata_violations(data), [])

    def test_value_repeating_another_field(self):
        data = {"categories": ["Engineering"], "metadata": {"teams": ["Engineering"]}}
        self.assertEqual(
            metadata_violations(data), ["metadata['teams'] repeats categories"]
        )

    def test_empty_values_are_exempt(self):
        data = {
            "categories": [],
            "metadata": {"pay": [], "deadline": None, "note": "", "extra": {}},
        }
        self.assertEqual(metadata_violations(data), [])

    def test_boolean_is_not_a_metadata_value(self):
        self.assertEqual(
            metadata_violations({"metadata": {"remote": False}}),
            [f"metadata['remote'] {_NOT_VALUE}"],
        )

    def test_list_of_objects_is_not_a_metadata_value(self):
        data = {"metadata": {"pay": [{"min_cents": 19000000}]}}
        self.assertEqual(metadata_violations(data), [f"metadata['pay'] {_NOT_VALUE}"])

    def test_object_is_not_a_metadata_value(self):
        data = {"metadata": {"range": {"min": 1}}}
        self.assertEqual(metadata_violations(data), [f"metadata['range'] {_NOT_VALUE}"])


if __name__ == "__main__":
    unittest.main()
