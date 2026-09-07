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
