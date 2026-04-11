import json
import unittest
from unittest.mock import MagicMock

from scraper.silver_worker import SilverWorker, SilverWorkerConfig


class TestSilverWorker(unittest.TestCase):
    def setUp(self):
        self.config = SilverWorkerConfig(
            redis_host="localhost",
            redis_port=6379,
            queue_name="test_silver_queue",
            log_level="ERROR",
        )
        self.worker = SilverWorker(self.config)
        self.worker.redis = MagicMock()

    def test_process_message_valid(self):
        # Slice 1: Should just process without error.
        message = json.dumps({"url": "http://example.com/job/1"})

        try:
            self.worker.process_message(message)
        except Exception as e:
            self.fail(f"process_message raised Exception unexpectedly: {e}")

    def test_process_message_missing_url(self):
        message = json.dumps({"other_data": "test"})

        # Should handle silently for now
        self.worker.process_message(message)

    def test_process_message_invalid_json(self):
        message = "invalid json"

        # Should catch JSONDecodeError internally
        self.worker.process_message(message)


if __name__ == "__main__":
    unittest.main()
