"""Snapshot-based test bases.

A snapshot pins the values a real captured page implies, so the generated tests exercise
the adapter's actual parsing rather than shape-only checks a stub could satisfy.
"""

import inspect
import json
import re
from collections.abc import Iterator
from pathlib import Path

from adapters.adapters.base import DetailMapping, IndexMapping
from adapters.adapters.mapping import load_mapping_file

_METADATA_KEY = re.compile(r"[a-z][a-z0-9_]*")
_OTHER_SILVER_FIELDS = (
    "title",
    "company_name",
    "employment_type",
    "locations",
    "categories",
    "description",
)


def _is_empty(value: object) -> bool:
    """Whether *value* is null or an empty string, list or object."""
    return value is None or value == "" or value == [] or value == {}


def _is_metadata_value(value: object) -> bool:
    """Whether *value* is a string, a number or a list of those."""

    def is_scalar(item: object) -> bool:
        return isinstance(item, str) or (
            isinstance(item, (int, float)) and not isinstance(item, bool)
        )

    if isinstance(value, list):
        return all(is_scalar(item) for item in value)
    return is_scalar(value)


def _strings(value: object) -> Iterator[str]:
    """Every string in *value*, descending through lists and object values."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def metadata_violations(data: dict) -> list[str]:
    """What in *data*'s ``metadata`` breaks the rules for that field, in key order."""
    metadata = data.get("metadata")
    if metadata is None:
        return []
    if not isinstance(metadata, dict):
        return ["metadata is not an object"]
    violations: list[str] = []
    for key, value in metadata.items():
        if not isinstance(key, str) or _METADATA_KEY.fullmatch(key) is None:
            violations.append(f"metadata key {key!r} is not lower snake_case")
        if any(
            s.strip().lower().startswith(("http://", "https://"))
            for s in _strings(value)
        ):
            violations.append(f"metadata[{key!r}] holds a URL")
        if _is_empty(value):
            continue
        for field in _OTHER_SILVER_FIELDS:
            if field in data and data[field] == value:
                violations.append(f"metadata[{key!r}] repeats {field}")
                break
        if not _is_metadata_value(value):
            violations.append(
                f"metadata[{key!r}] is not a string, a number or a list of them"
            )
    return violations


class DiscoverySnapshotTest:
    """Assert a DiscoveryAdapter reproduces a captured listing snapshot.

    Combine with ``unittest.TestCase``. Subclasses set ``adapter_cls`` and
    ``fixture_dir``. Fixtures live at ``<test dir>/fixtures/<fixture_dir>/`` as
    ``index.html`` (cleaned page) and ``expected.json``
    (``{"url", "job_links", "next_page_links"}``).

    Links are compared as **exact** sets: the adapter must return neither fewer (a
    broken or too-narrow selector) nor more (over-selection — a selector matching
    elements the lean input pruned away but the full ``index.html`` still contains) than
    the snapshot.
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
        # A snapshot the orchestrator did not write may omit the key entirely, which
        # must fail the exact-set comparison like an empty list rather than raise
        # KeyError.
        found = self.adapter.get_job_links(self.snapshot_html, self._url())
        self._assert_matches(found, self.snapshot.get("job_links", []), "job links")

    def test_next_page_links_match_snapshot(self):
        found = self.adapter.get_next_page_links(self.snapshot_html, self._url())
        expected = self.snapshot.get("next_page_links", [])
        self._assert_matches(found, expected, "next page")

    def test_empty_page_returns_no_links(self):
        empty = "<html><body></body></html>"
        self.assertEqual(self.adapter.get_job_links(empty, self._url()), [])
        self.assertEqual(self.adapter.get_next_page_links(empty, self._url()), [])

    def test_snapshot_pins_at_least_one_job_link(self):
        self.assertTrue(
            self.snapshot.get("job_links"),
            f"{self.fixture_dir}: snapshot pins no job links, so this suite proves "
            "nothing an adapter could get wrong",
        )


class ExtractionSnapshotTest:
    """Assert an ExtractionAdapter reproduces a captured detail-page snapshot.

    Combine with ``unittest.TestCase``. Subclasses set ``adapter_cls`` and
    ``fixture_dir``. Fixtures live at ``<test dir>/fixtures/<fixture_dir>/`` as
    ``detail.html`` (cleaned page) and ``expected.json`` (the Silver dict). Fields are
    compared by type: scalars exactly, list fields as sets, and ``description`` by
    equality (leading/trailing whitespace aside). The description is the adapter's
    deterministic ``_markdown.html_to_markdown`` output, so pinning it exactly makes the
    snapshot a precise regression guard: an adapter change or a markdownify upgrade
    that reformats it fails loudly.

    The fields the Silver table stores non-nullably — title, company_name, description
    — must be present in the output or the test fails loudly: a dropped one would reach
    ingest as a null and either be masked or rejected row-by-row in production. The
    remaining fields are nullable or DB-defaulted, so an adapter may omit them. Values,
    regardless, are only matched for the fields the snapshot pins (what the page
    actually states). A field the truth agent could not ground is not asserted.
    ``metadata`` is never compared with the snapshot, because each agent names its keys
    independently. ``test_metadata_conforms`` checks the output's own metadata instead.
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

    def test_metadata_conforms(self):
        if not isinstance(self.data, dict):
            return
        violations = metadata_violations(self.data)
        self.assertEqual(violations, [], f"{self.fixture_dir}: {violations}")

    def test_description_matches_snapshot(self):
        # A null or non-string description (a snapshot the orchestrator did not write
        # may hold anything) is treated as unpinned rather than raising from .strip().
        expected = self.snapshot.get("description")
        if isinstance(expected, str) and expected.strip():
            actual = (self.data.get("description") or "").strip()
            self.assertEqual(actual, expected.strip(), "description")

    def test_snapshot_pins_a_title_and_a_description(self):
        title = self.snapshot.get("title")
        description = self.snapshot.get("description")
        # A non-string value (a truth-agent snapshot the orchestrator did not write
        # could hold anything) is treated as unpinned rather than raising from .strip().
        title_text = title.strip() if isinstance(title, str) else ""
        description_text = description.strip() if isinstance(description, str) else ""
        self.assertTrue(
            title_text and description_text,
            f"{self.fixture_dir}: snapshot pins no title or no description, so this "
            "suite proves nothing an adapter could get wrong",
        )


def _contains_node(haystack: object, needle: object) -> bool:
    """Return whether *needle* occurs as a node of *haystack*, by recursive walk.

    Structural equality against a node, never a substring of serialised text,
    because a projection's serialisation can appear in the response's text without any
    node of the response equalling the projection's shape.
    """
    if haystack == needle:
        return True
    if isinstance(haystack, dict):
        return any(_contains_node(value, needle) for value in haystack.values())
    if isinstance(haystack, list):
        return any(_contains_node(item, needle) for item in haystack)
    return False


class IndexMappingSnapshotTest:
    """Assert an index mapping reproduces a captured API response's snapshot.

    Combine with ``unittest.TestCase``. Subclasses set ``basename``, from which both
    the fixture directory and the mapping document path are derived. Fixtures live at
    ``<test dir>/fixtures/<basename>/`` as ``index.json`` (the captured response,
    parsed) and ``expected.json`` (``{"url", "job_links"}``); the mapping document
    lives at ``<test dir>/mappings/<basename>.json``.
    """

    basename = None

    def _fixtures_dir(self) -> Path:
        return Path(inspect.getfile(type(self))).parent / "fixtures" / self.basename

    def _mapping_path(self) -> Path:
        return (
            Path(inspect.getfile(type(self))).parent
            / "mappings"
            / f"{self.basename}.json"
        )

    def setUp(self):
        if self.basename is None:
            self.fail("basename is not set")
        fixtures = self._fixtures_dir()
        self.document = json.loads((fixtures / "index.json").read_text())
        self.snapshot = json.loads((fixtures / "expected.json").read_text())
        self.mapping = load_mapping_file(self._mapping_path())

    def test_document_is_an_index_mapping(self):
        self.assertIsInstance(self.mapping, IndexMapping)

    def test_snapshot_names_its_url(self):
        url = self.snapshot.get("url")
        self.assertTrue(
            isinstance(url, str) and url,
            f"{self.basename}: snapshot names no URL to resolve references against",
        )

    def test_posting_urls_match_snapshot(self):
        refs = self.mapping.references(self.document, self.snapshot["url"])
        found = {ref.url for ref in refs}
        expected = set(self.snapshot.get("job_links", []))
        self.assertEqual(
            found,
            expected,
            f"job links — missing: {sorted(expected - found)}; "
            f"extra: {sorted(found - expected)}",
        )

    def test_reference_documents_come_from_the_response(self):
        # The base URL only resolves relative posting_url values, so a placeholder is
        # enough: a reference document's identity does not depend on it.
        refs = self.mapping.references(self.document, "https://example.com")
        for ref in refs:
            if ref.document is None:
                continue
            self.assertTrue(
                _contains_node(self.document, ref.document),
                f"reference document for {ref.url} is not a node of the captured "
                "response",
            )

    def test_snapshot_pins_at_least_one_job_link(self):
        self.assertTrue(
            self.snapshot.get("job_links"),
            f"{self.basename}: snapshot pins no job links, so this suite proves "
            "nothing an adapter could get wrong",
        )


class DetailMappingSnapshotTest:
    """Assert a detail mapping reproduces a captured posting's snapshot.

    Combine with ``unittest.TestCase``. Subclasses set ``basename``, from which both
    the fixture directory and the mapping document path are derived. Fixtures live at
    ``<test dir>/fixtures/<basename>/`` as ``detail.json`` (the captured posting,
    parsed) and ``expected.json`` (the Silver dict); the mapping document lives at
    ``<test dir>/mappings/<basename>.json``. Field comparison rules mirror
    ExtractionSnapshotTest's exactly, decorrelating the truth agent (which grounds
    what the posting states) from the document (which declares what its author could
    express).
    """

    basename = None

    _SCALAR_FIELDS = ("title", "company_name", "employment_type")
    _LIST_FIELDS = ("locations", "categories")
    _REQUIRED_FIELDS = ("title", "company_name", "description")

    def _fixtures_dir(self) -> Path:
        return Path(inspect.getfile(type(self))).parent / "fixtures" / self.basename

    def _mapping_path(self) -> Path:
        return (
            Path(inspect.getfile(type(self))).parent
            / "mappings"
            / f"{self.basename}.json"
        )

    def setUp(self):
        if self.basename is None:
            self.fail("basename is not set")
        fixtures = self._fixtures_dir()
        self.document = json.loads((fixtures / "detail.json").read_text())
        self.snapshot = json.loads((fixtures / "expected.json").read_text())
        self.mapping = load_mapping_file(self._mapping_path())
        # An index document has no to_silver, and erroring here would report an
        # AttributeError for every test instead of the one that names the kind.
        self.data = (
            self.mapping.to_silver(self.document)
            if isinstance(self.mapping, DetailMapping)
            else {}
        )

    def test_document_is_a_detail_mapping(self):
        self.assertIsInstance(self.mapping, DetailMapping)

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

    def test_metadata_conforms(self):
        if not isinstance(self.data, dict):
            return
        violations = metadata_violations(self.data)
        self.assertEqual(violations, [], f"{self.basename}: {violations}")

    def test_description_matches_snapshot(self):
        expected = self.snapshot.get("description")
        if isinstance(expected, str) and expected.strip():
            actual = (self.data.get("description") or "").strip()
            self.assertEqual(actual, expected.strip(), "description")

    def test_snapshot_pins_a_title_and_a_description(self):
        title = self.snapshot.get("title")
        description = self.snapshot.get("description")
        title_text = title.strip() if isinstance(title, str) else ""
        description_text = description.strip() if isinstance(description, str) else ""
        self.assertTrue(
            title_text and description_text,
            f"{self.basename}: snapshot pins no title or no description, so this "
            "suite proves nothing an adapter could get wrong",
        )
