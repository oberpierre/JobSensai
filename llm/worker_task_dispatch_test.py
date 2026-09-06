import json
import unittest
from unittest.mock import MagicMock, patch

from llm.worker import LLMWorker, _adapter_names


class TestProcessTask(unittest.TestCase):
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

    def test_process_task_discovery_routes_to_snapshot_flow(self):
        self.mock_redis.set.return_value = True

        # Orchestration only: the discovery flow generates then runs the suite once.
        self.worker._learn_discovery = MagicMock()
        self.worker._run_adapter_tests = MagicMock(return_value=(True, "PASSED"))
        self.worker.release_learning = MagicMock()

        task_payload = json.dumps(
            {
                "domain": "newboard.com",
                "url": "https://newboard.com/jobs",
                "html": "<html/>",
            }
        ).encode("utf-8")
        self.worker.process_task(task_payload, "discovery_learning_tasks")

        self.worker._learn_discovery.assert_called_once_with(
            "newboard.com", "https://newboard.com/jobs", "<html/>"
        )
        self.worker._run_adapter_tests.assert_called_once()
        self.worker.release_learning.assert_called_once_with(
            "newboard.com", "discovery"
        )

    def test_process_task_extraction_routes_to_snapshot_flow(self):
        self.mock_redis.set.return_value = True

        # The extraction queue drives the same generate-then-test-once flow.
        self.worker._learn_extraction = MagicMock()
        self.worker._run_adapter_tests = MagicMock(return_value=(True, "PASSED"))
        self.worker.release_learning = MagicMock()

        task_payload = json.dumps(
            {"url": "https://newboard.com/job/1", "html_content": "<html/>"}
        ).encode("utf-8")
        self.worker.process_task(task_payload, "extraction_learning_tasks")

        self.worker._learn_extraction.assert_called_once_with(
            "newboard.com", "https://newboard.com/job/1", "<html/>"
        )
        self.worker._run_adapter_tests.assert_called_once()
        self.worker.release_learning.assert_called_once_with(
            "newboard.com", "extraction"
        )

    def _run_extraction_task(self, passed: bool, test_output: str = "TEST LOG"):
        """Drive one extraction task past generation with a canned test result."""
        self.mock_redis.set.return_value = True
        self.worker._learn_extraction = MagicMock(
            return_value=_adapter_names("newboard.com", "extraction")
        )
        self.worker._run_adapter_tests = MagicMock(return_value=(passed, test_output))

        task_payload = json.dumps(
            {"url": "https://newboard.com/job/1", "html_content": "<html/>"}
        ).encode("utf-8")
        return self.worker.process_task(task_payload, "extraction_learning_tasks")

    def _assert_lease_released(self):
        self.mock_redis.delete.assert_called_with(
            "LEARNING_IN_PROGRESS:extraction:newboard.com"
        )

    def test_green_run_publishes_and_releases_the_lease(self):
        self._run_extraction_task(passed=True)

        kwargs = self.mock_publisher.publish.call_args.kwargs
        self.assertEqual(kwargs["basename"], "newboard_com_extraction_v1")
        self.assertEqual(kwargs["adapter_class"], "NewboardComExtractionAdapter")
        self.assertEqual(kwargs["domain"], "newboard.com")
        self.assertEqual(kwargs["adapter_type"], "extraction")
        self.assertTrue(kwargs["passed"])
        # The suite's output travels to the publisher so it can land in the PR body.
        self.assertEqual(kwargs["test_output"], "TEST LOG")
        self._assert_lease_released()

    def test_red_run_still_publishes_for_review(self):
        """A failing suite should be opened as a draft PR, not dropped."""
        self._run_extraction_task(passed=False, test_output="FAILED: 1 test")

        kwargs = self.mock_publisher.publish.call_args.kwargs
        self.assertFalse(kwargs["passed"])
        self.assertEqual(kwargs["test_output"], "FAILED: 1 test")
        self._assert_lease_released()

    def test_failed_publish_releases_the_lease_so_the_next_crawl_retries(self):
        """No PR exists, so the gh check will not skip it next time."""
        self.mock_publisher.publish.return_value = None
        self._run_extraction_task(passed=True)
        self._assert_lease_released()

    def test_only_lease_marker_is_written(self):
        """Sets a lease to prevent concurrent adapter generations."""
        self._run_extraction_task(passed=True)
        set_keys = {call.args[0] for call in self.mock_redis.set.call_args_list}
        self.assertEqual(set_keys, {"LEARNING_IN_PROGRESS:extraction:newboard.com"})

    def test_existing_pr_skips_the_regeneration_run(self):
        """A open PR will prevent adapter generation like the lease."""
        self.mock_publisher.has_existing_pr.return_value = True
        self._run_extraction_task(passed=True)

        self.mock_publisher.has_existing_pr.assert_called_once_with(
            "newboard_com_extraction_v1"
        )
        self.worker._learn_extraction.assert_not_called()
        self.mock_publisher.publish.assert_not_called()
        # The lease is dropped, not held: it means "learning", not "recently checked".
        self._assert_lease_released()

    def test_unknown_pr_state_requeues_the_task(self):
        """A skip would lose the task entirely, whereas a requeue only delays it."""
        self.mock_publisher.has_existing_pr.return_value = None
        self.mock_redis.set.return_value = True
        self.worker._learn_extraction = MagicMock(
            return_value=_adapter_names("newboard.com", "extraction")
        )
        self.worker._run_adapter_tests = MagicMock(return_value=(True, "TEST LOG"))

        task_payload = json.dumps(
            {"url": "https://newboard.com/job/1", "html_content": "<html/>"}
        ).encode("utf-8")
        result = self.worker.process_task(task_payload, "extraction_learning_tasks")

        self.mock_redis.lpush.assert_called_once_with(
            "extraction_learning_tasks", task_payload
        )
        self.assertIs(result, True)
        self.worker._learn_extraction.assert_not_called()
        self.mock_publisher.publish.assert_not_called()

    def test_unknown_pr_state_stops_the_worker_when_publish_becomes_unavailable(self):
        """A credential that dies mid-run must not requeue forever unchecked."""
        self.mock_publisher.has_existing_pr.return_value = None
        self.mock_publisher.can_publish.return_value = False
        self.mock_redis.set.return_value = True

        task_payload = json.dumps(
            {"url": "https://newboard.com/job/1", "html_content": "<html/>"}
        ).encode("utf-8")
        result = self.worker.process_task(task_payload, "extraction_learning_tasks")

        self.mock_redis.lpush.assert_called_once_with(
            "extraction_learning_tasks", task_payload
        )
        self.assertIs(result, True)
        self.assertFalse(self.worker.running)

    def test_known_pr_state_does_not_requeue(self):
        """A PR that already exists is work already done, so the task is dropped."""
        self.mock_publisher.has_existing_pr.return_value = True
        result = self._run_extraction_task(passed=True)

        self.mock_redis.lpush.assert_not_called()
        self.assertIs(result, False)
        self.worker._learn_extraction.assert_not_called()
        self.mock_publisher.publish.assert_not_called()
        self._assert_lease_released()

    def test_pr_check_happens_only_after_the_lease_is_won(self):
        """Concurrent pages of one board are absorbed by the lease, not by gh calls."""
        self.mock_redis.set.return_value = None  # lease already held
        task_payload = json.dumps(
            {"url": "https://newboard.com/job/1", "html_content": "<html/>"}
        ).encode("utf-8")
        self.worker.process_task(task_payload, "extraction_learning_tasks")

        self.mock_publisher.has_existing_pr.assert_not_called()

    @patch("llm.worker.logger")
    def test_process_task_no_domain_or_url(self, mock_logger):
        """Task with neither domain nor url must log an error and not touch Redis."""
        task_payload = json.dumps({}).encode("utf-8")
        self.worker.process_task(task_payload, "extraction_learning_tasks")

        self.assertTrue(mock_logger.error.called)
        self.assertEqual(self.mock_redis.set.call_count, 0)

    def test_process_task_domain_from_url(self):
        """Domain should be extracted from url when domain field is absent."""
        self.mock_redis.set.return_value = None  # Lock fails → early return

        task_payload = json.dumps(
            {"url": "http://newboard.com/job/1", "html": "<html/>"}
        ).encode("utf-8")
        self.worker.process_task(task_payload, "extraction_learning_tasks")

        self.mock_redis.set.assert_called_once_with(
            "LEARNING_IN_PROGRESS:extraction:newboard.com", "1", nx=True, ex=1800
        )

    @patch("llm.worker.logger")
    def test_process_task_already_learning(self, mock_logger):
        self.mock_redis.set.return_value = None

        task_payload = json.dumps(
            {"domain": "newboard.com", "url": "http://newboard.com/job/1"}
        ).encode("utf-8")
        self.worker.process_task(task_payload, "extraction_learning_tasks")

        mock_logger.info.assert_called_with(
            "Learning already in progress for domain: %s", "newboard.com"
        )
        self.mock_redis.set.assert_called_once()


if __name__ == "__main__":
    unittest.main()
