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
