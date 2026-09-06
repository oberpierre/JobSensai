import importlib
import os
import unittest
from unittest.mock import MagicMock, patch

import llm.worker as worker_module
from llm.worker import LLMWorker


class TestLearningLease(unittest.TestCase):
    def setUp(self):
        self.mock_redis = MagicMock()
        self.mock_publisher = MagicMock()
        self.mock_publisher.publish.return_value = "https://github.com/acme/repo/pull/7"
        self.mock_publisher.has_existing_pr.return_value = False
        with patch("redis.Redis", return_value=self.mock_redis):
            self.worker = LLMWorker(
                redis_host="localhost",
                redis_port=6379,
                publisher=self.mock_publisher,
            )

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

    def test_start_learning_uses_lease_ttl_env_var(self):
        # The default is a module-level constant read at import, so the env var has to
        # be in place before the module (re)loads for start_learning to see it.
        with patch.dict(os.environ, {"LEARNING_LEASE_TTL_SECONDS": "60"}):
            importlib.reload(worker_module)
            self.addCleanup(importlib.reload, worker_module)
            with patch("redis.Redis", return_value=self.mock_redis):
                worker = worker_module.LLMWorker(
                    redis_host="localhost",
                    redis_port=6379,
                    publisher=self.mock_publisher,
                )
            self.mock_redis.set.return_value = True
            worker.start_learning("acme.com", "discovery")
            self.mock_redis.set.assert_called_with(
                "LEARNING_IN_PROGRESS:discovery:acme.com", "1", nx=True, ex=60
            )

    def test_start_learning_explicit_ttl_wins_over_env_var(self):
        self.mock_redis.set.return_value = True
        self.worker.start_learning("acme.com", "discovery", ttl=99)
        self.mock_redis.set.assert_called_with(
            "LEARNING_IN_PROGRESS:discovery:acme.com", "1", nx=True, ex=99
        )

    def test_release_learning_drops_the_lease_and_records_nothing(self):
        self.worker.release_learning("google.com", "extraction")
        self.mock_redis.delete.assert_called_with(
            "LEARNING_IN_PROGRESS:extraction:google.com"
        )
        self.assertEqual(self.mock_redis.set.call_count, 0)


if __name__ == "__main__":
    unittest.main()
