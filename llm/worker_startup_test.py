import os
import unittest
from unittest.mock import MagicMock, patch

from llm.worker import _WORKSPACE_ROOT, LLMWorker, _worker_from_env, main


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


class TestBaseBranchFromEnv(unittest.TestCase):
    def _publisher_call(self, env: dict[str, str], remove: bool = False):
        with (
            patch.dict(os.environ, env),
            patch("llm.worker.redis.Redis"),
            patch("llm.worker.Publisher") as mock_publisher,
        ):
            if remove:
                os.environ.pop("LEARNING_BASE_BRANCH", None)
            worker = _worker_from_env()
        mock_publisher.assert_called_once()
        self.assertIs(worker.publisher, mock_publisher.return_value)
        return mock_publisher.call_args

    def test_publishes_against_the_configured_branch(self):
        call = self._publisher_call({"LEARNING_BASE_BRANCH": "feature/api-boards"})
        self.assertEqual(
            call.kwargs,
            {"repo_root": _WORKSPACE_ROOT, "base_branch": "feature/api-boards"},
        )

    def test_defaults_to_main_when_unset(self):
        call = self._publisher_call({}, remove=True)
        self.assertEqual(call.kwargs["base_branch"], "main")

    def test_defaults_to_main_when_empty(self):
        call = self._publisher_call({"LEARNING_BASE_BRANCH": ""})
        self.assertEqual(call.kwargs["base_branch"], "main")


class TestRunLogsBaseState(unittest.TestCase):
    def _worker(self, can_publish: bool, log_result=None):
        publisher = MagicMock()
        publisher.can_publish.return_value = can_publish
        publisher.log_base_state.return_value = log_result
        with patch("llm.worker.redis.Redis"):
            worker = LLMWorker(publisher=publisher)
        return worker, publisher

    def test_logs_once_before_the_first_poll(self):
        worker, publisher = self._worker(True)
        parent = MagicMock()
        parent.attach_mock(publisher.log_base_state, "log_base_state")
        parent.attach_mock(worker.redis_client.brpop, "brpop")

        def stop(*_args, **_kwargs):
            worker.running = False

        worker.redis_client.brpop.side_effect = stop

        self.assertTrue(worker.run())
        names = [c[0] for c in parent.mock_calls]
        self.assertEqual(names[0], "log_base_state")
        self.assertEqual(names.count("log_base_state"), 1)
        self.assertIn("brpop", names)

    def test_a_worker_that_cannot_publish_logs_nothing(self):
        worker, publisher = self._worker(False)
        self.assertFalse(worker.run())
        publisher.log_base_state.assert_not_called()

    def test_the_result_never_depends_on_the_log(self):
        worker, _ = self._worker(True, log_result=False)

        def stop(*_args, **_kwargs):
            worker.running = False

        worker.redis_client.brpop.side_effect = stop
        self.assertTrue(worker.run())


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
