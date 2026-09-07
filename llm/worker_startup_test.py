import os
import unittest
from unittest.mock import MagicMock, patch

from llm.worker import LLMWorker, _worker_from_env, main


class TestRedisClientCredentials(unittest.TestCase):
    def setUp(self):
        self.mock_publisher = MagicMock()

    def test_redis_client_authenticates_with_credentials_from_env(self):
        with (
            patch.dict(
                os.environ,
                {"REDIS_USERNAME": "user-llm", "REDIS_PASSWORD": "password"},
            ),
            patch("redis.Redis") as mock_redis_cls,
        ):
            LLMWorker(
                redis_host="localhost", redis_port=6379, publisher=self.mock_publisher
            )
        self.assertEqual(mock_redis_cls.call_args.kwargs["username"], "user-llm")
        self.assertEqual(mock_redis_cls.call_args.kwargs["password"], "password")

    def test_redis_client_has_no_credentials_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDIS_USERNAME", None)
            os.environ.pop("REDIS_PASSWORD", None)
            with patch("redis.Redis") as mock_redis_cls:
                LLMWorker(
                    redis_host="localhost",
                    redis_port=6379,
                    publisher=self.mock_publisher,
                )
        self.assertIsNone(mock_redis_cls.call_args.kwargs["username"])
        self.assertIsNone(mock_redis_cls.call_args.kwargs["password"])


class TestWorkerFromEnv(unittest.TestCase):
    @patch("llm.worker.redis.Redis")
    def test_reads_ollama_and_redis_from_env(self, mock_redis):
        env = {
            "OLLAMA_HOST": "gpu-box",
            "OLLAMA_PORT": "9999",
            "REDIS_HOST": "cluster-redis",
            "REDIS_PORT": "6380",
            "REDIS_USERNAME": "user",
            "REDIS_PASSWORD": "password",
        }
        with patch.dict(os.environ, env):
            worker = _worker_from_env()

        self.assertEqual(worker.llm_url, "http://gpu-box:9999")
        mock_redis.assert_called_once_with(
            host="cluster-redis", port=6380, username="user", password="password"
        )

    @patch("llm.worker.redis.Redis")
    def test_tolerates_a_scheme_in_ollama_host(self, mock_redis):
        # A scheme prefix must not produce http://http://...
        with patch.dict(os.environ, {"OLLAMA_HOST": "http://127.0.0.1"}):
            worker = _worker_from_env()

        self.assertEqual(worker.llm_url, "http://127.0.0.1:11434")

    @patch("llm.worker.redis.Redis")
    def test_falls_back_to_localhost_defaults(self, mock_redis):
        with patch.dict(os.environ, {}, clear=True):
            worker = _worker_from_env()

        self.assertEqual(worker.llm_url, "http://localhost:11434")
        mock_redis.assert_called_once_with(
            host="localhost", port=6379, username=None, password=None
        )


class TestMain(unittest.TestCase):
    @patch("llm.worker._worker_from_env")
    def test_exits_non_zero_when_the_worker_never_starts(self, mock_worker_from_env):
        worker = MagicMock()
        worker.run.return_value = False
        mock_worker_from_env.return_value = worker

        with self.assertRaises(SystemExit) as ctx:
            main()
        self.assertNotEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
