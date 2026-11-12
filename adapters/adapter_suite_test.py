import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from adapters.adapters import adapter_test


def _module() -> types.ModuleType:
    class Passes(unittest.TestCase):
        def test_ok(self) -> None:
            pass

    module = types.ModuleType("fake")
    module.Passes = Passes  # type: ignore[attr-defined]
    return module


class TestLoadTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name in ("alpha_test", "beta_test", "base_test"):
            (Path(tmp.name) / f"{name}.py").write_text("")
        self.dir = Path(tmp.name)

    def _load(
        self, only: str | None, raises: tuple[str, ...] = ()
    ) -> tuple[unittest.TestResult, MagicMock]:
        importlib = MagicMock()

        def import_module(name: str) -> types.ModuleType:
            if name.rsplit(".", 1)[-1] in raises:
                raise ImportError("boom")
            return _module()

        importlib.import_module.side_effect = import_module
        env = {} if only is None else {"TESTBRIDGE_TEST_ONLY": only}
        with (
            patch.object(adapter_test, "_ADAPTERS_DIR", self.dir),
            patch.object(adapter_test, "importlib", importlib),
            patch.dict(os.environ, env),
        ):
            if only is None:
                os.environ.pop("TESTBRIDGE_TEST_ONLY", None)
            suite = adapter_test.load_tests(
                unittest.TestLoader(), unittest.TestSuite(), None
            )
        result = unittest.TestResult()
        suite.run(result)
        return result, importlib

    def _imported(self, importlib: MagicMock) -> list[str]:
        return [c.args[0] for c in importlib.import_module.call_args_list]

    def _assert_unmatched(self, only: str) -> None:
        result, importlib = self._load(only)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.failures), 1)
        self.assertIn(only, result.failures[0][1])
        self.assertEqual(result.errors, [])
        importlib.import_module.assert_not_called()

    def _assert_all(self, only: str | None) -> None:
        result, importlib = self._load(only)
        self.assertEqual(result.testsRun, 2)
        self.assertEqual(result.failures, [])
        self.assertEqual(
            self._imported(importlib),
            ["adapters.adapters.alpha_test", "adapters.adapters.beta_test"],
        )

    def test_unset_loads_every_candidate(self) -> None:
        self._assert_all(None)

    def test_a_filter_loads_only_that_module(self) -> None:
        result, importlib = self._load("beta_test")
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.failures, [])
        self.assertEqual(self._imported(importlib), ["adapters.adapters.beta_test"])

    def test_a_filter_matching_nothing_fails(self) -> None:
        self._assert_unmatched("gamma_test")

    def test_a_prefix_of_a_candidate_matches_nothing(self) -> None:
        self._assert_unmatched("beta")

    def test_a_skipped_name_matches_nothing(self) -> None:
        self._assert_unmatched("base_test")

    def test_an_import_error_in_the_selected_module_fails(self) -> None:
        result, _ = self._load("beta_test", raises=("beta_test",))
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.failures), 1)
        self.assertIn("adapters.adapters.beta_test", result.failures[0][1])
        self.assertIn("boom", result.failures[0][1])

    def test_an_unfiltered_import_error_is_skipped(self) -> None:
        result, _ = self._load(None, raises=("beta_test",))
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])

    def test_an_empty_filter_loads_every_candidate(self) -> None:
        self._assert_all("")


if __name__ == "__main__":
    unittest.main()
