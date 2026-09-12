"""Writes the files a learned adapter consists of: fixture, snapshot test, adapter."""

import json
import os
import re
from pathlib import Path
from typing import NamedTuple

# Paths resolved relative to this file so they work in both bazel run and tests.
# During `bazel run`, BUILD_WORKSPACE_DIRECTORY points to the real checkout root,
# which is where generated adapter files are written.
_WORKSPACE_ROOT = Path(
    os.environ.get("BUILD_WORKSPACE_DIRECTORY", str(Path(__file__).parent.parent))
)
_ADAPTERS_DIR = _WORKSPACE_ROOT / "adapters" / "adapters"

# The generated test is deterministic boilerplate: all grounded assertions live in the
# snapshot base class it imports and subclasses.
_TEST_TEMPLATE = """import unittest

from adapters.adapters.snapshot import {snapshot_base}
from {module_path} import {adapter_class}


class {test_class}({snapshot_base}, unittest.TestCase):
    adapter_cls = {adapter_class}
    fixture_dir = "{basename}"
"""

# A mapping document has no module to import: the snapshot base derives both the
# fixture directory and the document path from `basename` alone.
_MAPPING_TEST_TEMPLATE = """import unittest

from adapters.adapters.snapshot import {snapshot_base}


class {test_class}({snapshot_base}, unittest.TestCase):
    basename = "{basename}"
"""


def _domain_slug(domain: str) -> str:
    """Turn a domain into a valid Python module-name fragment.

    Lowercases and replaces every run of non-alphanumeric characters with a single
    underscore, e.g. ``job-boards.greenhouse.io`` -> ``job_boards_greenhouse_io``.
    ``domain.replace(".", "_")`` left hyphens in place and produced illegal module
    names for hyphenated boards.
    """
    return re.sub(r"[^a-z0-9]+", "_", domain.lower()).strip("_")


class AdapterNames(NamedTuple):
    basename: str
    module_path: str
    adapter_class: str
    test_class: str


class MappingNames(NamedTuple):
    basename: str
    test_class: str


_MAPPING_TYPES = frozenset({"index", "detail"})


def _mapping_names(domain: str, mapping_type: str, version: int = 1) -> MappingNames:
    """Derive the file/class names for a generated mapping document.

    Never derived by `_adapter_names`: its type argument is free-form and its
    caller falls back to `extraction` for anything that is not `discovery`, which
    would name a mapping document as though it were an adapter.
    """
    if mapping_type not in _MAPPING_TYPES:
        raise ValueError(f"unknown mapping type: {mapping_type!r}")
    slug = _domain_slug(domain)
    basename = f"{slug}_{mapping_type}_v{version}"
    pascal = "".join(part.capitalize() for part in slug.split("_") if part)
    test_class = f"Test{pascal}{mapping_type.capitalize()}Mapping"
    return MappingNames(basename=basename, test_class=test_class)


def _adapter_names(domain: str, adapter_type: str, version: int = 1) -> AdapterNames:
    """Derive the file/module/class names for a generated adapter.

    Both agents receive these names up-front, so the generated test's import line and
    the adapter's class definition line up without either agent seeing the other.
    """
    slug = _domain_slug(domain)
    basename = f"{slug}_{adapter_type}_v{version}"
    pascal = "".join(part.capitalize() for part in slug.split("_") if part)
    adapter_class = f"{pascal}{adapter_type.capitalize()}Adapter"
    return AdapterNames(
        basename=basename,
        module_path=f"adapters.adapters.{basename}",
        adapter_class=adapter_class,
        test_class=f"Test{adapter_class}",
    )


def staged_paths(basename: str, kind: str) -> list[str]:
    """The paths one generated artifact's files are staged at for a PR.

    Mirrors the write destinations below, both keyed off the same *basename*, so a
    pathspec that ``git add`` is given always matches what was actually written.
    *kind* is required: a caller naming a kind nothing writes is a programming
    error, and returning the adapter triple for it would hand ``git add`` a
    pathspec matching nothing, which is fatal rather than a no-op.
    """
    if kind == "adapter":
        return [
            f"adapters/adapters/{basename}.py",
            f"adapters/adapters/{basename}_test.py",
            f"adapters/adapters/fixtures/{basename}",
        ]
    if kind == "mapping":
        return [
            f"adapters/adapters/mappings/{basename}.json",
            f"adapters/adapters/{basename}_test.py",
            f"adapters/adapters/fixtures/{basename}",
        ]
    raise ValueError(f"unknown kind: {kind!r}")


def _write_fixture(basename: str, filename: str, content: str) -> Path:
    fixture_dir = _ADAPTERS_DIR / "fixtures" / basename
    fixture_dir.mkdir(parents=True, exist_ok=True)
    path = fixture_dir / filename
    path.write_text(content)
    return path


def _write_snapshot(
    names: AdapterNames,
    fixture_filename: str,
    page: str,
    expected: dict,
    snapshot_base: str,
) -> None:
    """Write the page fixture, the grounded ``expected.json``, and the test.

    Shared by both flows: each builds its own ``expected`` dict from the HTML it
    grounded, then hands it here so the three files land the same way regardless
    of adapter type.
    """
    _write_fixture(names.basename, fixture_filename, page)
    _write_fixture(names.basename, "expected.json", json.dumps(expected, indent=2))
    test_source = _TEST_TEMPLATE.format(
        module_path=names.module_path,
        adapter_class=names.adapter_class,
        test_class=names.test_class,
        basename=names.basename,
        snapshot_base=snapshot_base,
    )
    (_ADAPTERS_DIR / f"{names.basename}_test.py").write_text(test_source)


def _read_base_code() -> str:
    """Read now rather than at import: tests patch ``_ADAPTERS_DIR`` afterwards."""
    return (_ADAPTERS_DIR / "base.py").read_text()


def _write_adapter(names: AdapterNames, adapter_src: str) -> None:
    """Write the finished adapter source the code agent produced."""
    (_ADAPTERS_DIR / f"{names.basename}.py").write_text(adapter_src)


def _write_mapping(names: MappingNames, document_text: str) -> None:
    """Write the mapping document.

    Creates its parent directory: ``adapters/adapters/mappings/`` exists in the
    checkout only because a ``.gitkeep`` holds it.
    """
    mappings_dir = _ADAPTERS_DIR / "mappings"
    mappings_dir.mkdir(parents=True, exist_ok=True)
    (mappings_dir / f"{names.basename}.json").write_text(document_text)


def _write_mapping_snapshot(
    names: MappingNames,
    fixture_filename: str,
    body_text: str,
    expected: dict,
    snapshot_base: str,
) -> None:
    """Write the response fixture, the grounded ``expected.json``, and the test.

    Not `_write_snapshot`, widened: that helper reads `.module_path` and
    `.adapter_class`, which `MappingNames` does not have.
    """
    _write_fixture(names.basename, fixture_filename, body_text)
    _write_fixture(names.basename, "expected.json", json.dumps(expected, indent=2))
    test_source = _MAPPING_TEST_TEMPLATE.format(
        test_class=names.test_class,
        basename=names.basename,
        snapshot_base=snapshot_base,
    )
    (_ADAPTERS_DIR / f"{names.basename}_test.py").write_text(test_source)
