"""Tests for the mapping snapshot bases against synthetic documents and mappings.

Mirrors snapshot_test.py's shape for the HTML bases: each outer test builds a
fixture directory and a mapping document in a tempfile.TemporaryDirectory, wires it
in with an overridden ``_fixtures_dir``/``_mapping_path``, then runs the inner
TestCase and inspects the result — the same pattern
snapshot_test.py::TestDiscoverySnapshotTest._snapshot_case uses.
"""

import json
import tempfile
import unittest
from pathlib import Path

from adapters.adapters._markdown import html_to_markdown
from adapters.adapters.snapshot import (
    DetailMappingSnapshotTest,
    IndexMappingSnapshotTest,
)

_BASE_INDEX_MAPPING = {
    "version": 1,
    "type": "index",
    "domains": ["example.com"],
    "jmespath": {"postings": "jobs[]", "job_url": "absolute_url"},
}

_BASE_DETAIL_MAPPING = {
    "version": 1,
    "type": "detail",
    "domains": ["example.com"],
    "jmespath": {
        "title": "title",
        "company_name": "'Acme'",
        "employment_type": "employment_type",
        "locations": "offices[].name",
        "categories": "tags",
        "description": "markdown(unescape(content))",
    },
}

_DETAIL_DOCUMENT = {
    "title": "Staff Engineer",
    "employment_type": "Full-time",
    "offices": [{"name": "Berlin"}, {"name": "Remote"}],
    "tags": ["Engineering"],
    "content": "&lt;p&gt;We build things.&lt;/p&gt;",
}

_DETAIL_DESCRIPTION = html_to_markdown("<p>We build things.</p>")

_DETAIL_SNAPSHOT = {
    "title": "Staff Engineer",
    "company_name": "Acme",
    "employment_type": "Full-time",
    "locations": ["Berlin", "Remote"],
    "categories": ["Engineering"],
    "description": _DETAIL_DESCRIPTION,
}


def _run(test_cls) -> unittest.TestResult:
    suite = unittest.TestLoader().loadTestsFromTestCase(test_cls)
    return suite.run(unittest.TestResult())


def _run_one(test_cls, name: str) -> unittest.TestResult:
    outcome = unittest.TestResult()
    test_cls(name).run(outcome)
    return outcome


def _index_case(
    root: Path, basename: str, mapping: dict, response: dict, snapshot: dict
):
    fixtures = root / "fixtures" / basename
    fixtures.mkdir(parents=True)
    (fixtures / "index.json").write_text(json.dumps(response))
    (fixtures / "expected.json").write_text(json.dumps(snapshot))
    mapping_path = root / "mappings" / f"{basename}.json"
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(json.dumps(mapping))

    class _Case(IndexMappingSnapshotTest, unittest.TestCase):
        def _fixtures_dir(self_inner) -> Path:
            return fixtures

        def _mapping_path(self_inner) -> Path:
            return mapping_path

    _Case.basename = basename
    return _Case


def _detail_case(
    root: Path, basename: str, mapping: dict, document: dict, snapshot: dict
):
    fixtures = root / "fixtures" / basename
    fixtures.mkdir(parents=True)
    (fixtures / "detail.json").write_text(json.dumps(document))
    (fixtures / "expected.json").write_text(json.dumps(snapshot))
    mapping_path = root / "mappings" / f"{basename}.json"
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(json.dumps(mapping))

    class _Case(DetailMappingSnapshotTest, unittest.TestCase):
        def _fixtures_dir(self_inner) -> Path:
            return fixtures

        def _mapping_path(self_inner) -> Path:
            return mapping_path

    _Case.basename = basename
    return _Case


class TestIndexMappingSnapshotTest(unittest.TestCase):
    def test_passes_when_mapping_reproduces_snapshot(self):
        response = {
            "jobs": [
                {"absolute_url": "https://example.com/jobs/1", "title": "A"},
                {"absolute_url": "https://example.com/jobs/2", "title": "B"},
            ]
        }
        snapshot = {
            "url": "https://example.com/jobs",
            "job_links": [
                "https://example.com/jobs/1",
                "https://example.com/jobs/2",
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            case = _index_case(
                Path(tmp), "basic", _BASE_INDEX_MAPPING, response, snapshot
            )
            result = _run(case)
        self.assertTrue(result.wasSuccessful(), result.failures or result.errors)

    def test_fails_when_mapping_misses_links(self):
        snapshot = {
            "url": "https://example.com/jobs",
            "job_links": ["https://example.com/jobs/1"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            case = _index_case(
                Path(tmp), "empty_jobs", _BASE_INDEX_MAPPING, {"jobs": []}, snapshot
            )
            result = _run(case)
        self.assertFalse(result.wasSuccessful())

    def test_fails_when_mapping_over_selects(self):
        response = {
            "jobs": [
                {"absolute_url": "https://example.com/jobs/1", "title": "A"},
                {"absolute_url": "https://example.com/not-a-job", "title": "B"},
            ]
        }
        snapshot = {
            "url": "https://example.com/jobs",
            "job_links": ["https://example.com/jobs/1"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            case = _index_case(
                Path(tmp), "over_selecting", _BASE_INDEX_MAPPING, response, snapshot
            )
            result = _run(case)
        # A subset comparison survives the missing-links case above and not this one.
        self.assertFalse(result.wasSuccessful())

    def test_fails_when_document_is_actually_a_detail_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = _index_case(
                Path(tmp),
                "wrong_kind",
                _BASE_DETAIL_MAPPING,
                {"title": "Engineer"},
                {"url": "https://example.com/jobs", "job_links": ["x"]},
            )
            outcome = _run_one(case, "test_document_is_an_index_mapping")
        self.assertFalse(outcome.wasSuccessful())
        self.assertEqual(outcome.errors, [])
        self.assertEqual(len(outcome.failures), 1)

    def test_none_document_is_permitted_for_an_address_only_feed(self):
        mapping = {
            "version": 1,
            "type": "index",
            "domains": ["example.com"],
            "jmespath": {"postings": "jobs[]", "job_url": "@"},
        }
        response = {
            "jobs": ["https://example.com/jobs/1", "https://example.com/jobs/2"]
        }
        snapshot = {
            "url": "https://example.com/jobs",
            "job_links": [
                "https://example.com/jobs/1",
                "https://example.com/jobs/2",
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            case = _index_case(Path(tmp), "addresses_only", mapping, response, snapshot)
            result = _run(case)
        self.assertTrue(result.wasSuccessful(), result.failures or result.errors)

    def test_fails_when_reference_document_is_not_a_node_of_the_response(self):
        # jobs[].{url: absolute_url, title: title} builds an object with different
        # keys than any element the response actually carries.
        mapping = {
            "version": 1,
            "type": "index",
            "domains": ["example.com"],
            "jmespath": {
                "postings": "jobs[].{url: absolute_url, title: title}",
                "job_url": "url",
            },
        }
        response = {
            "jobs": [{"absolute_url": "https://example.com/jobs/1", "title": "A"}]
        }
        snapshot = {
            "url": "https://example.com/jobs",
            "job_links": ["https://example.com/jobs/1"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            case = _index_case(
                Path(tmp), "synthesized_object", mapping, response, snapshot
            )
            outcome = _run_one(case, "test_reference_documents_come_from_the_response")
        self.assertFalse(outcome.wasSuccessful())

    def test_job_urls_match_snapshot_resolves_relative_url_against_snapshot_url(self):
        mapping = {
            "version": 1,
            "type": "index",
            "domains": ["boards.example.org"],
            "jmespath": {"postings": "jobs[]", "job_url": "path"},
        }
        response = {"jobs": [{"path": "/jobs/1"}, {"path": "/jobs/2"}]}
        snapshot = {
            "url": "https://boards.example.org/jobs",
            "job_links": [
                "https://boards.example.org/jobs/1",
                "https://boards.example.org/jobs/2",
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            case = _index_case(
                Path(tmp), "relative_job_url", mapping, response, snapshot
            )
            outcome = _run_one(case, "test_job_urls_match_snapshot")
        self.assertTrue(outcome.wasSuccessful(), outcome.failures)

    def test_guard_fails_with_a_message_when_url_key_is_absent(self):
        response = {"jobs": [{"absolute_url": "https://example.com/jobs/1"}]}
        snapshot = {"job_links": ["https://example.com/jobs/1"]}
        with tempfile.TemporaryDirectory() as tmp:
            case = _index_case(
                Path(tmp), "no_url_key", _BASE_INDEX_MAPPING, response, snapshot
            )
            outcome = _run_one(case, "test_snapshot_names_its_url")
        self.assertFalse(outcome.wasSuccessful())
        message = str(outcome.failures[0][1])
        self.assertIn("no_url_key", message)
        self.assertIn("no URL", message)

    def test_guard_fails_when_snapshot_pins_no_job_links(self):
        snapshot = {"url": "https://example.com/jobs", "job_links": []}
        with tempfile.TemporaryDirectory() as tmp:
            case = _index_case(
                Path(tmp), "no_job_links", _BASE_INDEX_MAPPING, {"jobs": []}, snapshot
            )
            outcome = _run_one(case, "test_snapshot_pins_at_least_one_job_link")
        self.assertFalse(outcome.wasSuccessful())
        message = str(outcome.failures[0][1])
        self.assertIn("no_job_links", message)
        self.assertIn("proves nothing", message)

    def test_malformed_document_surfaces_mapping_error_in_output(self):
        mapping = {
            "version": 1,
            "type": "index",
            "domains": ["example.com"],
            "jmespath": {
                "postings": "jobs[]",
                "job_url": "absolute_url",
                "bogus_key": "foo",
            },
        }
        snapshot = {"url": "https://example.com/jobs", "job_links": ["x"]}
        with tempfile.TemporaryDirectory() as tmp:
            case = _index_case(
                Path(tmp), "unknown_key", mapping, {"jobs": []}, snapshot
            )
            result = _run(case)
        self.assertFalse(result.wasSuccessful())
        combined = "".join(msg for _, msg in result.errors)
        self.assertIn("MappingError", combined)
        self.assertIn("unknown jmespath key", combined)


class TestDetailMappingSnapshotTest(unittest.TestCase):
    def test_passes_when_mapping_reproduces_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = _detail_case(
                Path(tmp),
                "basic",
                _BASE_DETAIL_MAPPING,
                _DETAIL_DOCUMENT,
                _DETAIL_SNAPSHOT,
            )
            result = _run(case)
        self.assertTrue(result.wasSuccessful(), result.failures or result.errors)

    def test_fails_on_wrong_scalar_field(self):
        snapshot = {**_DETAIL_SNAPSHOT, "title": "Something Else"}
        with tempfile.TemporaryDirectory() as tmp:
            case = _detail_case(
                Path(tmp),
                "wrong_title",
                _BASE_DETAIL_MAPPING,
                _DETAIL_DOCUMENT,
                snapshot,
            )
            result = _run(case)
        self.assertFalse(result.wasSuccessful())

    def test_fails_when_required_field_missing_though_snapshot_unpinned(self):
        mapping = {
            **_BASE_DETAIL_MAPPING,
            "jmespath": dict(_BASE_DETAIL_MAPPING["jmespath"]),
        }
        del mapping["jmespath"]["description"]
        snapshot = {k: v for k, v in _DETAIL_SNAPSHOT.items() if k != "description"}
        with tempfile.TemporaryDirectory() as tmp:
            case = _detail_case(
                Path(tmp), "drops_description", mapping, _DETAIL_DOCUMENT, snapshot
            )
            result = _run(case)
        self.assertFalse(result.wasSuccessful())
        self.assertTrue(
            any("required_field" in str(f[0]) for f in result.failures), result.failures
        )

    def test_passes_when_optional_list_field_is_omitted(self):
        mapping = {
            **_BASE_DETAIL_MAPPING,
            "jmespath": dict(_BASE_DETAIL_MAPPING["jmespath"]),
        }
        del mapping["jmespath"]["categories"]
        snapshot = {k: v for k, v in _DETAIL_SNAPSHOT.items() if k != "categories"}
        with tempfile.TemporaryDirectory() as tmp:
            case = _detail_case(
                Path(tmp), "drops_categories", mapping, _DETAIL_DOCUMENT, snapshot
            )
            result = _run(case)
        self.assertTrue(result.wasSuccessful(), result.failures or result.errors)

    def test_fails_when_description_differs(self):
        snapshot = {**_DETAIL_SNAPSHOT, "description": "Completely unrelated content."}
        with tempfile.TemporaryDirectory() as tmp:
            case = _detail_case(
                Path(tmp),
                "wrong_description",
                _BASE_DETAIL_MAPPING,
                _DETAIL_DOCUMENT,
                snapshot,
            )
            result = _run(case)
        self.assertFalse(result.wasSuccessful())

    def test_passes_when_snapshot_pins_a_subset_of_silver_keys(self):
        # The assertion that stops whole-dict equality creeping back in: the mapping
        # computes every field, the snapshot pins only two of them.
        subset = {
            "title": _DETAIL_SNAPSHOT["title"],
            "description": _DETAIL_SNAPSHOT["description"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            case = _detail_case(
                Path(tmp),
                "subset_snapshot",
                _BASE_DETAIL_MAPPING,
                _DETAIL_DOCUMENT,
                subset,
            )
            outcome = _run_one(case, "test_scalar_fields_match")
        self.assertTrue(outcome.wasSuccessful(), outcome.failures or outcome.errors)

    def test_fails_when_document_is_actually_an_index_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = _detail_case(
                Path(tmp),
                "wrong_kind",
                _BASE_INDEX_MAPPING,
                {"jobs": []},
                {"title": "x", "company_name": "y", "description": "z"},
            )
            outcome = _run_one(case, "test_document_is_a_detail_mapping")
        self.assertFalse(outcome.wasSuccessful())

    def test_guard_fails_when_snapshot_pins_no_title_or_description(self):
        snapshot = {**_DETAIL_SNAPSHOT, "title": "", "description": "   "}
        with tempfile.TemporaryDirectory() as tmp:
            case = _detail_case(
                Path(tmp),
                "blank_snapshot",
                _BASE_DETAIL_MAPPING,
                _DETAIL_DOCUMENT,
                snapshot,
            )
            outcome = _run_one(case, "test_snapshot_pins_a_title_and_a_description")
        self.assertFalse(outcome.wasSuccessful())
        message = str(outcome.failures[0][1])
        self.assertIn("blank_snapshot", message)
        self.assertIn("proves nothing", message)


if __name__ == "__main__":
    unittest.main()
