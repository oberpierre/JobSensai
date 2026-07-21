"""Snapshot-based test bases.

A snapshot pins the values a real captured page implies, so the generated tests exercise
the adapter's actual parsing rather than shape-only checks a stub could satisfy.
"""

import inspect
import json
from pathlib import Path


class DiscoverySnapshotTest:
    """Assert a DiscoveryAdapter reproduces a captured listing snapshot.

    Combine with ``unittest.TestCase``. Subclasses set ``adapter_cls`` and
    ``fixture_dir``; fixtures live at ``<test dir>/fixtures/<fixture_dir>/`` as
    ``index.html`` (cleaned page) and ``expected.json``
    (``{"url", "job_links", "next_page_links"}``).

    Links are compared as **exact** sets: the adapter must return neither fewer (a
    broken or too-narrow selector) nor more (over-selection — a selector matching
    elements the lean input pruned away but the full ``index.html`` still contains) than
    the snapshot. When the truth agent under-enumerates, the human corrects
    ``expected.json`` during review.
    """

    adapter_cls = None
    fixture_dir = None

    def _fixtures_dir(self) -> Path:
        return Path(inspect.getfile(type(self))).parent / "fixtures" / self.fixture_dir

    def setUp(self):
        fixtures = self._fixtures_dir()
        self.snapshot_html = (fixtures / "index.html").read_text()
        self.snapshot = json.loads((fixtures / "expected.json").read_text())
        self.adapter = self.adapter_cls()

    def _url(self) -> str:
        return self.snapshot.get("url", "https://example.com/jobs")

    def _assert_matches(self, found: list, expected: list, label: str):
        found_set, expected_set = set(found), set(expected)
        self.assertEqual(
            found_set,
            expected_set,
            f"{label} — missing: {sorted(expected_set - found_set)}; "
            f"extra: {sorted(found_set - expected_set)}",
        )

    def test_job_links_match_snapshot(self):
        found = self.adapter.get_job_links(self.snapshot_html, self._url())
        self._assert_matches(found, self.snapshot["job_links"], "job links")

    def test_next_page_links_match_snapshot(self):
        found = self.adapter.get_next_page_links(self.snapshot_html, self._url())
        expected = self.snapshot.get("next_page_links", [])
        self._assert_matches(found, expected, "next page")

    def test_empty_page_returns_no_links(self):
        empty = "<html><body></body></html>"
        self.assertEqual(self.adapter.get_job_links(empty, self._url()), [])
        self.assertEqual(self.adapter.get_next_page_links(empty, self._url()), [])


class ExtractionSnapshotTest:
    """Assert an ExtractionAdapter reproduces a captured detail-page snapshot.

    Combine with ``unittest.TestCase``. Subclasses set ``adapter_cls`` and
    ``fixture_dir``; fixtures live at ``<test dir>/fixtures/<fixture_dir>/`` as
    ``detail.html`` (cleaned page) and ``expected.json`` (the Silver dict). Fields are
    compared by type: scalars exactly, list fields as sets, and ``description`` by
    equality (leading/trailing whitespace aside). The description is the adapter's
    deterministic ``_markdown.html_to_markdown`` output, so pinning it exactly makes the
    snapshot a precise regression guard — an adapter change or a markdownify upgrade
    that reformats it fails loudly. Until a human certifies the snapshot to the
    adapter's real output, first generation is expected to be red (draft PR), by design.

    The fields the Silver table stores non-nullably — title, company_name, description
    — must be present in the output or the test fails loudly: a dropped one would reach
    ingest as a null and either be masked or rejected row-by-row in production. The
    remaining fields are nullable or DB-defaulted, so an adapter may omit them. Values,
    regardless, are only matched for the fields the snapshot pins (what the page
    actually states); a field the truth agent could not ground is not asserted.
    """

    adapter_cls = None
    fixture_dir = None

    _SCALAR_FIELDS = ("title", "company_name", "employment_type")
    _LIST_FIELDS = ("locations", "categories")
    _REQUIRED_FIELDS = ("title", "company_name", "description")

    def _fixtures_dir(self) -> Path:
        return Path(inspect.getfile(type(self))).parent / "fixtures" / self.fixture_dir

    def setUp(self):
        fixtures = self._fixtures_dir()
        self.snapshot_html = (fixtures / "detail.html").read_text()
        self.snapshot = json.loads((fixtures / "expected.json").read_text())
        url = self.snapshot.get("url", "https://example.com/job/1")
        self.data = self.adapter_cls().extract(self.snapshot_html, url)

    def test_returns_a_dict(self):
        self.assertIsInstance(self.data, dict)

    def test_returns_every_required_field(self):
        missing = [f for f in self._REQUIRED_FIELDS if f not in self.data]
        self.assertEqual(missing, [], f"dropped required Silver fields: {missing}")

    def test_scalar_fields_match(self):
        for field in self._SCALAR_FIELDS:
            if field in self.snapshot:
                self.assertEqual(self.data.get(field), self.snapshot[field], field)

    def test_list_fields_match(self):
        for field in self._LIST_FIELDS:
            if field in self.snapshot:
                self.assertEqual(
                    set(self.data.get(field) or []), set(self.snapshot[field]), field
                )

    def test_description_matches_snapshot(self):
        expected = self.snapshot.get("description", "").strip()
        if expected:
            actual = (self.data.get("description") or "").strip()
            self.assertEqual(actual, expected, "description")
