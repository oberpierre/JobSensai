import json
import unittest
from unittest.mock import MagicMock, mock_open, patch

from llm.worker import LLMWorker


class TestLLMWorker(unittest.TestCase):
    def setUp(self):
        self.mock_redis = MagicMock()

        # Patch redis.Redis before instantiating LLMWorker
        with patch("redis.Redis", return_value=self.mock_redis):
            self.worker = LLMWorker(redis_host="localhost", redis_port=6379)

    def test_is_learning_in_progress(self):
        self.mock_redis.get.return_value = b"1"
        self.assertTrue(self.worker.is_learning_in_progress("google.com"))
        self.mock_redis.get.assert_called_with("LEARNING_IN_PROGRESS:google.com")

        self.mock_redis.get.return_value = None
        self.assertFalse(self.worker.is_learning_in_progress("yahoo.com"))

    def test_start_learning_success(self):
        self.mock_redis.set.return_value = True
        self.assertTrue(self.worker.start_learning("bing.com"))
        self.mock_redis.set.assert_called_with(
            "LEARNING_IN_PROGRESS:bing.com", "1", nx=True, ex=1800
        )

    def test_start_learning_failure_already_exists(self):
        self.mock_redis.set.return_value = (
            None  # redis-py returns None on nx=True failure
        )
        self.assertFalse(self.worker.start_learning("bing.com"))

    def test_complete_learning(self):
        self.worker.complete_learning("google.com")
        self.mock_redis.delete.assert_called_with("LEARNING_IN_PROGRESS:google.com")
        self.mock_redis.set.assert_called_with("LEARNING_COMPLETE:google.com", "1")

    @patch("llm.worker.LLMModel")
    @patch("llm.worker.logger")
    @patch("builtins.open", new_callable=mock_open, read_data="class BaseAdapter: pass")
    @patch("os.path.join", side_effect=lambda *args: "/".join(args))
    def test_process_task_full_pipeline(
        self, mock_join, mock_open_file, mock_logger, mock_llm_class
    ):
        self.mock_redis.set.return_value = True  # Lock acquired
        mock_llm_instance = mock_llm_class.return_value
        mock_llm_instance.generate_adapter.return_value = (
            "class NewAdapter(BaseAdapter): pass\n"
            "# --- TEST CODE ---\n"
            "def test_new(): pass"
        )

        self.worker.parse_llm_response = MagicMock(
            return_value=("class NewAdapter(BaseAdapter): pass", "def test_new(): pass")
        )
        self.worker.validate_code = MagicMock(return_value=True)
        self.worker.save_and_commit = MagicMock()
        self.worker.complete_learning = MagicMock()

        task_payload = json.dumps(
            {"domain": "newboard.com", "raw_html": "<html></html>"}
        ).encode("utf-8")
        self.worker.process_task(task_payload)

        self.worker.save_and_commit.assert_called_once()
        self.worker.complete_learning.assert_called_once_with("newboard.com")

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

    def test_validate_code_success(self):
        adapter_code = """
from adapaters.adapters.base import BaseAdapter
class NewAdapter(BaseAdapter):
    def get_job_links(self, html, url): return []
    def get_next_page_links(self, html, url): return []
    def extract(self, html, url): return {"title": "Job"}
"""
        test_code = "def test_new(): pass"
        self.assertTrue(
            self.worker.validate_code(
                "example.com",
                adapter_code,
                test_code,
                "<html></html>",
                "http://example.com",
            )
        )

    def test_validate_code_syntax_error(self):
        adapter_code = "class NewAdapter(BaseAdapter): invalid syntax"
        self.assertFalse(
            self.worker.validate_code(
                "example.com", adapter_code, None, "<html></html>", "http://example.com"
            )
        )

    def test_validate_code_no_base_adapter(self):
        adapter_code = "class NewAdapter: pass"
        self.assertFalse(
            self.worker.validate_code(
                "example.com", adapter_code, None, "<html></html>", "http://example.com"
            )
        )

    @patch("subprocess.run")
    def test_run_generated_tests_success(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "PASSED"

        adapter_code = "class NewAdapter(BaseAdapter): pass"
        test_code = "def test_logic(): assert True"

        self.assertTrue(
            self.worker.run_generated_tests("example.com", adapter_code, test_code)
        )

    @patch("subprocess.run")
    def test_run_generated_tests_failure(self, mock_run):
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = "FAILED"

        adapter_code = "class NewAdapter(BaseAdapter): pass"
        test_code = "def test_logic(): assert False"

        self.assertFalse(
            self.worker.run_generated_tests("example.com", adapter_code, test_code)
        )

    @patch("llm.worker.LLMModel")
    def test_validate_code_retry_success(self, mock_llm_class):
        mock_llm_instance = mock_llm_class.return_value
        # First call fails (invalid syntax), second call succeeds
        mock_llm_instance.generate_adapter.return_value = """
from adapaters.adapters.base import BaseAdapter
class NewAdapter(BaseAdapter):
    def get_job_links(self, html, url): return []
    def get_next_page_links(self, html, url): return []
    def extract(self, html, url): return {"title": "Fixed Job"}
"""

        # Initial code with syntax error
        bad_adapter_code = "class NewAdapter(BaseAdapter): invalid syntax"

        # We need to mock open for retry_generation
        with patch("builtins.open", mock_open(read_data="class BaseAdapter: pass")):
            result = self.worker.validate_code(
                "example.com",
                bad_adapter_code,
                None,
                "<html></html>",
                "http://example.com",
            )

        self.assertTrue(result)
        self.assertEqual(mock_llm_instance.generate_adapter.call_count, 1)

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.system")
    def test_save_and_commit(self, mock_system, mock_open_file):
        self.worker.save_and_commit("example.com", "adapter code", "test code")

        # Check if files were written
        self.assertEqual(mock_open_file.call_count, 2)

        # Check git commands
        self.assertTrue(
            any(
                "git checkout -b feature/adapter-example_com-v1" in str(call)
                for call in mock_system.call_args_list
            )
        )
        self.assertTrue(
            any("git commit -m" in str(call) for call in mock_system.call_args_list)
        )

    @patch("llm.worker.logger")
    def test_process_task_missing_domain(self, mock_logger):
        task_payload = json.dumps({"url": "http://newboard.com/job/1"}).encode("utf-8")
        self.worker.process_task(task_payload)

        self.assertTrue(mock_logger.error.called)
        self.assertEqual(self.mock_redis.set.call_count, 0)

    @patch("llm.worker.logger")
    def test_process_task_already_learning(self, mock_logger):
        self.mock_redis.set.return_value = None  # Lock failed

        task_payload = json.dumps(
            {"domain": "newboard.com", "url": "http://newboard.com/job/1"}
        ).encode("utf-8")
        self.worker.process_task(task_payload)

        mock_logger.info.assert_called_with(
            "Learning already in progress for domain: %s", "newboard.com"
        )
        self.mock_redis.set.assert_called_once()
