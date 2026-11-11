import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm import adapter_files
from llm.adapter_files import (
    _adapter_names,
    _mapping_names,
    _write_adapter,
    _write_mapping_snapshot,
    _write_snapshot,
    staged_paths,
)
from llm.generated_lint import lint_generated

RUFF = os.path.abspath(os.environ["RUFF_BIN"])
RUFF_CONFIG = os.path.abspath(os.environ["RUFF_CONFIG"])

# Imports out of order and unseparated, and a return line over the line length that
# the formatter can wrap.
SOURCE = (
    """from urllib.parse import urljoin
import json
from adapters.adapters.base import ExtractionAdapter


class AcmeExtractionAdapter(ExtractionAdapter):
    domains = ["acme.com"]

    def extract(self, html: str, url: str) -> dict:
        return {"title": urljoin(url, "a"), "company_name": json.dumps(html), """
    '"description": "a long description value", "metadata": {}}\n'
)

UNFIXABLE_SOURCE = """import json

from adapters.adapters.base import ExtractionAdapter


class AcmeExtractionAdapter(ExtractionAdapter):
    domains = ["acme.com"]

    def extract(self, html: str, url: str) -> dict:
        unused = html.strip()
        return {"title": json.dumps(url)}
"""


class TestLintGenerated(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copy(RUFF_CONFIG, self.root / ".ruff.toml")
        adapters_dir = self.root / "adapters" / "adapters"
        adapters_dir.mkdir(parents=True)
        patcher = patch.object(adapter_files, "_ADAPTERS_DIR", adapters_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _hook(self, path: Path) -> tuple[int, int]:
        cfg = str(self.root / ".ruff.toml")
        check = subprocess.run(
            [RUFF, "check", "--config", cfg, str(path)], capture_output=True
        )
        fmt = subprocess.run(
            [RUFF, "format", "--check", "--force-exclude", "--config", cfg, str(path)],
            capture_output=True,
        )
        return check.returncode, fmt.returncode

    def _write_extraction(self, source: str):
        names = _adapter_names("acme.com", "extraction")
        _write_snapshot(
            names,
            "detail.html",
            "<html></html>",
            {"url": "https://acme.com/jobs/1"},
            "ExtractionSnapshotTest",
        )
        _write_adapter(names, source)
        adapters_dir = self.root / "adapters" / "adapters"
        return names, [
            adapters_dir / f"{names.basename}_test.py",
            adapters_dir / f"{names.basename}.py",
        ]

    def test_the_mapping_test_template_passes_the_hook_for_a_long_hostname(self):
        names = _mapping_names("boards-api.greenhouse.io", "index")
        _write_mapping_snapshot(
            names,
            "index.json",
            "{}",
            {
                "url": "https://boards-api.greenhouse.io/v1/boards/x/jobs",
                "job_links": [],
            },
            "IndexMappingSnapshotTest",
        )
        test_file = self.root / "adapters" / "adapters" / f"{names.basename}_test.py"
        self.assertNotEqual(self._hook(test_file)[0], 0)

        passed, _ = lint_generated(
            self.root, staged_paths(names.basename, "mapping"), (RUFF,)
        )

        self.assertTrue(passed)
        self.assertEqual(self._hook(test_file), (0, 0))

    def test_the_adapter_test_template_and_model_source_pass_the_hook(self):
        names, files = self._write_extraction(SOURCE)
        for f in files:
            self.assertNotEqual(self._hook(f)[0], 0, f.name)

        passed, _ = lint_generated(
            self.root, staged_paths(names.basename, "adapter"), (RUFF,)
        )

        self.assertTrue(passed)
        for f in files:
            self.assertEqual(self._hook(f), (0, 0), f.name)

    def test_what_ruff_cannot_fix_makes_the_result_red(self):
        names, _ = self._write_extraction(UNFIXABLE_SOURCE)

        passed, output = lint_generated(
            self.root, staged_paths(names.basename, "adapter"), (RUFF,)
        )

        self.assertFalse(passed)
        self.assertIn("F841", output)

    def test_nothing_to_lint_runs_nothing(self):
        with patch("llm.generated_lint.subprocess.run") as mock_run:
            result = lint_generated(
                self.root,
                [
                    "adapters/adapters/mappings/x_index_v1.json",
                    "adapters/adapters/fixtures/x_index_v1",
                ],
            )
        self.assertEqual(result, (True, ""))
        mock_run.assert_not_called()

    def test_a_missing_binary_is_a_red_result_not_an_exception(self):
        (self.root / "adapters" / "adapters" / "x_test.py").write_text("")
        passed, output = lint_generated(
            self.root, ["adapters/adapters/x_test.py"], ("/nonexistent/ruff",)
        )
        self.assertFalse(passed)
        self.assertIn("Could not run ruff", output)


if __name__ == "__main__":
    unittest.main()
