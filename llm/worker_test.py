import json
import unittest
from unittest.mock import MagicMock, patch

from llm.worker import LLMWorker


class TestLLMWorker(unittest.TestCase):
    def setUp(self):
        self.mock_redis = MagicMock()
        with patch("redis.Redis", return_value=self.mock_redis):
            self.worker = LLMWorker(redis_host="localhost", redis_port=6379)

    def test_is_learning_in_progress(self):
        self.mock_redis.get.return_value = b"1"
        self.assertTrue(self.worker.is_learning_in_progress("google.com", "discovery"))
        self.mock_redis.get.assert_called_with(
            "LEARNING_IN_PROGRESS:discovery:google.com"
        )

        self.mock_redis.get.return_value = None
        self.assertFalse(self.worker.is_learning_in_progress("yahoo.com", "extraction"))

    def test_start_learning_success(self):
        self.mock_redis.set.return_value = True
        self.assertTrue(self.worker.start_learning("bing.com", "discovery"))
        self.mock_redis.set.assert_called_with(
            "LEARNING_IN_PROGRESS:discovery:bing.com", "1", nx=True, ex=1800
        )

    def test_start_learning_failure_already_exists(self):
        self.mock_redis.set.return_value = None
        self.assertFalse(self.worker.start_learning("bing.com", "discovery"))

    def test_learning_lock_is_namespaced_by_adapter_type(self):
        """Discovery and extraction locks for one domain must not collide."""
        self.mock_redis.set.return_value = True
        self.worker.start_learning("acme.com", "discovery")
        self.worker.start_learning("acme.com", "extraction")
        keys = {call.args[0] for call in self.mock_redis.set.call_args_list}
        self.assertEqual(
            keys,
            {
                "LEARNING_IN_PROGRESS:discovery:acme.com",
                "LEARNING_IN_PROGRESS:extraction:acme.com",
            },
        )

    def test_complete_learning(self):
        self.worker.complete_learning("google.com", "extraction")
        self.mock_redis.delete.assert_called_with(
            "LEARNING_IN_PROGRESS:extraction:google.com"
        )
        self.mock_redis.set.assert_called_with(
            "LEARNING_COMPLETE:extraction:google.com", "1"
        )

    @patch("llm.worker.LLMModel")
    def test_process_task_full_pipeline(self, mock_llm_class):
        self.mock_redis.set.return_value = True

        mock_llm_instance = mock_llm_class.return_value
        mock_llm_instance.generate_adapter.return_value = (
            "class NewAdapter(DiscoveryAdapter): pass\n"
            "# --- TEST CODE ---\n"
            "def test_new(): pass"
        )

        # Replace sub-methods with mocks so we test orchestration only
        self.worker.parse_llm_response = MagicMock(
            return_value=(
                "class NewAdapter(DiscoveryAdapter): pass",
                "def test_new(): pass",
            )
        )
        self.worker._quick_validate = MagicMock(return_value=True)
        self.worker._write_test_and_verify = MagicMock(return_value=True)
        self.worker._commit = MagicMock()
        self.worker.complete_learning = MagicMock()

        task_payload = json.dumps(
            {"domain": "newboard.com", "html": "<html></html>"}
        ).encode("utf-8")
        self.worker.process_task(task_payload, "discovery_learning_tasks")

        self.worker._write_test_and_verify.assert_called_once()
        self.worker.complete_learning.assert_called_once_with(
            "newboard.com", "discovery"
        )

    def test_parse_llm_response_with_separator(self):
        response = "adapter code\n# --- TEST CODE ---\ntest code"
        adapter, test = self.worker.parse_llm_response(response)
        self.assertEqual(adapter, "adapter code")
        self.assertEqual(test, "test code")

    def test_parse_llm_response_without_separator(self):
        response = "adapter code only"
        adapter, test = self.worker.parse_llm_response(response)
        self.assertEqual(adapter, "adapter code only")
        self.assertIsNone(test)

    def test_parse_llm_response_empty_parts_become_none(self):
        response = "# --- TEST CODE ---"
        adapter, test = self.worker.parse_llm_response(response)
        self.assertIsNone(adapter)
        self.assertIsNone(test)

    def test_validate_code_discovery_success(self):
        adapter_code = (
            "from adapters.adapters.base import DiscoveryAdapter\n"
            "class NewAdapter(DiscoveryAdapter):\n"
            "    def get_job_links(self, html, url): return []\n"
            "    def get_next_page_links(self, html, url): return []\n"
        )
        self.assertTrue(
            self.worker.validate_code(
                "example.com",
                adapter_code,
                None,
                "<html></html>",
                "http://example.com",
                adapter_type="discovery",
            )
        )

    def test_validate_code_extraction_success(self):
        adapter_code = (
            "from adapters.adapters.base import ExtractionAdapter\n"
            "class NewAdapter(ExtractionAdapter):\n"
            "    def extract(self, html, url): return {'title': 'Job'}\n"
        )
        self.assertTrue(
            self.worker.validate_code(
                "example.com",
                adapter_code,
                None,
                "<html></html>",
                "http://example.com",
                adapter_type="extraction",
            )
        )

    def test_validate_code_syntax_error(self):
        self.assertFalse(
            self.worker.validate_code(
                "example.com",
                "class Broken(: invalid",
                None,
                "<html></html>",
                "http://example.com",
            )
        )

    def test_validate_code_wrong_base_class(self):
        adapter_code = "class NewAdapter: pass"
        self.assertFalse(
            self.worker.validate_code(
                "example.com",
                adapter_code,
                None,
                "<html></html>",
                "http://example.com",
            )
        )

    @patch("subprocess.run")
    def test_run_generated_tests_success(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "PASSED"
        self.assertTrue(
            self.worker.run_generated_tests(
                "example.com",
                (
                    "from adapters.adapters.base import DiscoveryAdapter\n"
                    "class A(DiscoveryAdapter): pass"
                ),
                "def test_logic(): assert True",
            )
        )

    @patch("subprocess.run")
    def test_run_generated_tests_failure(self, mock_run):
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = "FAILED"
        self.assertFalse(
            self.worker.run_generated_tests(
                "example.com",
                "class A: pass",
                "def test_logic(): assert False",
            )
        )

    @patch("llm.worker.subprocess.run")
    def test_save_and_commit(self, mock_subproc):
        mock_subproc.return_value.returncode = 0

        with (
            patch.object(self.worker, "_write_adapter_files") as mock_write,
            patch.object(self.worker, "_commit") as mock_commit,
        ):
            self.worker.save_and_commit(
                "example.com", "adapter code", "test code", "extraction"
            )

        mock_write.assert_called_once_with(
            "example.com", "adapter code", "test code", "extraction"
        )
        mock_commit.assert_called_once_with("example.com", "extraction")

    @patch("llm.worker.logger")
    def test_process_task_no_domain_or_url(self, mock_logger):
        """Task with neither domain nor url must log an error and not touch Redis."""
        task_payload = json.dumps({}).encode("utf-8")
        self.worker.process_task(task_payload)

        self.assertTrue(mock_logger.error.called)
        self.assertEqual(self.mock_redis.set.call_count, 0)

    def test_process_task_domain_from_url(self):
        """Domain should be extracted from url when domain field is absent."""
        self.mock_redis.set.return_value = None  # Lock fails → early return

        task_payload = json.dumps(
            {"url": "http://newboard.com/job/1", "html": "<html/>"}
        ).encode("utf-8")
        self.worker.process_task(task_payload)

        # No queue name → defaults to the extraction learning loop.
        self.mock_redis.set.assert_called_once_with(
            "LEARNING_IN_PROGRESS:extraction:newboard.com", "1", nx=True, ex=1800
        )

    @patch("llm.worker.logger")
    def test_process_task_already_learning(self, mock_logger):
        self.mock_redis.set.return_value = None

        task_payload = json.dumps(
            {"domain": "newboard.com", "url": "http://newboard.com/job/1"}
        ).encode("utf-8")
        self.worker.process_task(task_payload)

        mock_logger.info.assert_called_with(
            "Learning already in progress for domain: %s", "newboard.com"
        )
        self.mock_redis.set.assert_called_once()


if __name__ == "__main__":
    unittest.main()
