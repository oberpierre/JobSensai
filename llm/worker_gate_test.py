import unittest
from unittest.mock import MagicMock, patch

from llm.worker import _WORKSPACE_ROOT, LLMWorker

STAGED = ["adapters/adapters/x.py", "adapters/adapters/x_test.py"]


class TestRunAdapterTests(unittest.TestCase):
    def setUp(self):
        with patch("redis.Redis", return_value=MagicMock()):
            self.worker = LLMWorker(
                redis_host="localhost", redis_port=6379, publisher=MagicMock()
            )

    def _gate(self, lint, returncode, stdout=""):
        parent = MagicMock()
        with (
            patch("llm.worker.lint_generated", return_value=lint) as mock_lint,
            patch("llm.worker.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=returncode, stdout=stdout, stderr=""
            )
            parent.attach_mock(mock_lint, "lint")
            parent.attach_mock(mock_run, "run")
            result = self.worker._run_adapter_tests(STAGED)
        return result, parent

    def test_a_red_lint_makes_the_gate_red_and_ends_the_output(self):
        (passed, output), _ = self._gate((False, "LINT-OUT"), 0, "TESTS-OUT")
        self.assertIs(passed, False)
        self.assertIn("TESTS-OUT", output)
        self.assertTrue(output.endswith("LINT-OUT"))

    def test_a_red_test_run_makes_the_gate_red(self):
        (passed, _), _ = self._gate((True, ""), 1)
        self.assertIs(passed, False)

    def test_both_green_makes_the_gate_green(self):
        (passed, _), _ = self._gate((True, "ok"), 0)
        self.assertIs(passed, True)

    def test_lint_runs_once_with_the_staged_list_before_the_tests(self):
        _, parent = self._gate((True, ""), 0)
        parent.lint.assert_called_once_with(_WORKSPACE_ROOT, STAGED)
        names = [c[0] for c in parent.mock_calls]
        self.assertLess(names.index("lint"), names.index("run"))

    def test_the_test_run_is_filtered_to_the_artifacts_test_module(self):
        _, parent = self._gate((True, ""), 0)
        self.assertEqual(
            parent.run.call_args.args[0],
            [
                "bazel",
                "test",
                "//adapters:adapter_test",
                "--test_filter=x_test",
                "--test_output=errors",
            ],
        )

    def test_a_mapping_artifact_filters_on_its_own_test_module(self):
        staged = [
            "adapters/adapters/mappings/x_index_v1.json",
            "adapters/adapters/x_index_v1_test.py",
            "adapters/adapters/fixtures/x_index_v1",
        ]
        with (
            patch("llm.worker.lint_generated", return_value=(True, "")),
            patch("llm.worker.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            self.worker._run_adapter_tests(staged)
        self.assertEqual(mock_run.call_args.args[0][3], "--test_filter=x_index_v1_test")

    def test_staged_files_without_one_test_module_run_nothing(self):
        with (
            patch("llm.worker.lint_generated") as mock_lint,
            patch("llm.worker.subprocess.run") as mock_run,
            self.assertRaises(ValueError),
        ):
            self.worker._run_adapter_tests(["adapters/adapters/x.py"])
        mock_lint.assert_not_called()
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
