import json
import unittest
from unittest.mock import MagicMock, patch

from llm.worker import LLMWorker


class TestRunRefusesWithoutPublishAccess(unittest.TestCase):
    def setUp(self):
        self.mock_redis = MagicMock()
        self.mock_publisher = MagicMock()
        with patch("redis.Redis", return_value=self.mock_redis):
            self.worker = LLMWorker(
                redis_host="localhost",
                redis_port=6379,
                publisher=self.mock_publisher,
            )

    def test_run_returns_without_polling_when_publish_is_unavailable(self):
        self.mock_publisher.can_publish.return_value = False
        result = self.worker.run()
        self.mock_redis.brpop.assert_not_called()
        self.assertFalse(self.worker.running)
        self.assertFalse(result)


class TestRunStopsMidRunWhenPublishDies(unittest.TestCase):
    @patch("llm.worker.time.sleep")
    def test_run_returns_false_when_publish_dies_mid_run(self, mock_sleep):
        mock_redis = MagicMock()
        mock_publisher = MagicMock()
        # The first call gates the startup loop. The second is the mid-run recheck.
        mock_publisher.can_publish.side_effect = [True, False]
        mock_publisher.has_existing_pr.return_value = None
        mock_redis.set.return_value = True
        task_payload = json.dumps(
            {"url": "https://newboard.com/job/1", "html_content": "<html/>"}
        ).encode("utf-8")
        mock_redis.brpop.return_value = (b"extraction_learning_tasks", task_payload)
        with patch("redis.Redis", return_value=mock_redis):
            worker = LLMWorker(
                redis_host="localhost",
                redis_port=6379,
                publisher=mock_publisher,
            )

        result = worker.run()

        self.assertIs(result, False)
        # A stop caused by a publish failure must not also wait out the backoff.
        mock_sleep.assert_not_called()


class TestRunLoopRespectsRunningWithoutDerivingFromIt(unittest.TestCase):
    def setUp(self):
        self.mock_redis = MagicMock()
        self.mock_publisher = MagicMock()
        self.mock_publisher.can_publish.return_value = True
        with patch("redis.Redis", return_value=self.mock_redis):
            self.worker = LLMWorker(
                redis_host="localhost", redis_port=6379, publisher=self.mock_publisher
            )

    def test_return_value_is_independent_of_running(self):
        # Simulates a future, unrelated stop reason setting running directly.
        def stop_directly():
            self.worker.running = False
            return False

        self.worker.process_next_task = MagicMock(side_effect=stop_directly)
        self.assertTrue(self.worker.run())

    @patch("llm.worker.time.sleep")
    def test_ordinary_requeue_still_sleeps(self, mock_sleep):
        # Proves the backoff guard's other branch, without a publish failure.
        results = iter([True, False])

        def process_next_task():
            value = next(results)
            if not value:
                self.worker.running = False
            return value

        self.worker.process_next_task = MagicMock(side_effect=process_next_task)
        self.worker.run()
        mock_sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
