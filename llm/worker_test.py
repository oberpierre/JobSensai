import json
import unittest
from unittest.mock import MagicMock, patch

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

    @patch("llm.worker.logger")
    def test_process_task_success(self, mock_logger):
        self.mock_redis.set.return_value = True  # Lock acquired

        task_payload = json.dumps(
            {"domain": "newboard.com", "url": "http://newboard.com/job/1"}
        ).encode("utf-8")
        self.worker.process_task(task_payload)

        mock_logger.info.assert_called_with(
            "Starting learning for domain: %s", "newboard.com"
        )
        self.mock_redis.set.assert_called_once()

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
