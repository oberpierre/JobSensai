import json
import os
import unittest
from unittest.mock import MagicMock, patch

from llm.adapter_files import _mapping_names, staged_paths
from llm.learning_errors import TruthAgentUnreadable, UnlearnablePage
from llm.worker import LLMWorker

_DOMAIN = "boards-api.acme.com"
_URL = "https://boards-api.acme.com/v1/boards/acme/jobs"
_DOCUMENT = {"jobs": [{"id": 1, "absolute_url": "https://acme.com/jobs/1"}]}
_NAMES = _mapping_names(_DOMAIN, "index")
_DETAIL_NAMES = _mapping_names(_DOMAIN, "detail")


class TestProcessMappingTask(unittest.TestCase):
    def setUp(self):
        self.mock_redis = MagicMock()
        self.mock_publisher = MagicMock()
        self.mock_publisher.publish.return_value = "https://github.com/acme/repo/pull/9"
        self.mock_publisher.has_existing_pr.return_value = False
        with patch("redis.Redis", return_value=self.mock_redis):
            self.worker = LLMWorker(
                redis_host="localhost",
                redis_port=6379,
                publisher=self.mock_publisher,
            )

    def _payload(self, **overrides) -> bytes:
        task = {
            "artifact": "mapping",
            "domain": _DOMAIN,
            "url": _URL,
            "body": json.dumps(_DOCUMENT),
        }
        task.update(overrides)
        return json.dumps(task).encode("utf-8")

    def _run_green(self, queue_name: str = "discovery_learning_tasks"):
        """Drive one mapping task past generation with a canned green result."""
        self.mock_redis.set.return_value = True
        self.worker._run_adapter_tests = MagicMock(return_value=(True, "PASSED"))
        with patch(
            "llm.learning_task.learn_mapping",
            return_value=(_NAMES, "acme-test-model"),
        ) as mock_learn:
            result = self.worker.process_task(self._payload(), queue_name)
        return result, mock_learn

    # Proof 1: the artifact membership check

    def test_artifact_wrong_string_value_is_dropped_without_a_lease(self):
        payload = self._payload(artifact="index")
        result = self.worker.process_task(payload, "discovery_learning_tasks")
        self.assertIs(result, False)
        self.mock_redis.set.assert_not_called()

    def test_artifact_null_is_dropped_without_a_lease(self):
        payload = self._payload(artifact=None)
        result = self.worker.process_task(payload, "discovery_learning_tasks")
        self.assertIs(result, False)
        self.mock_redis.set.assert_not_called()

    # Checks 2-4: presence, before the lease

    def test_missing_domain_is_dropped_without_a_netloc_fallback(self):
        # url's netloc is the same host, so a fallback bug would not drop the
        # task at all, letting it proceed to take a lease under the mutation.
        payload = self._payload(domain="")
        result = self.worker.process_task(payload, "discovery_learning_tasks")
        self.assertIs(result, False)
        self.mock_redis.set.assert_not_called()

    def test_missing_url_is_dropped(self):
        payload = self._payload(url="")
        result = self.worker.process_task(payload, "discovery_learning_tasks")
        self.assertIs(result, False)
        self.mock_redis.set.assert_not_called()

    # Proof 2: validation before start_learning

    def test_missing_body_leaves_the_index_lease_unset(self):
        payload = self._payload(body="")
        result = self.worker.process_task(payload, "discovery_learning_tasks")
        self.assertIs(result, False)
        set_keys = {call.args[0] for call in self.mock_redis.set.call_args_list}
        self.assertNotIn(f"LEARNING_IN_PROGRESS:index:{_DOMAIN}", set_keys)

    # Proof 13: the budget check

    def test_non_positive_budget_drops_without_lease_or_requeue(self):
        payload = self._payload()
        with patch.dict(os.environ, {"INDEX_NUM_CTX": "2000"}):  # < 4096 reserve
            result = self.worker.process_task(payload, "discovery_learning_tasks")
        self.assertIs(result, False)
        self.mock_redis.set.assert_not_called()
        self.mock_redis.lpush.assert_not_called()

    # Proof 10: the data check, before the lease

    def test_non_json_body_is_dropped_before_the_lease(self):
        payload = self._payload(body="<html>502</html>")
        with patch("llm.learning_task.logger") as mock_logger:
            result = self.worker.process_task(payload, "discovery_learning_tasks")
        self.assertIs(result, False)
        self.mock_redis.set.assert_not_called()
        logged = [call.args for call in mock_logger.error.call_args_list]
        self.assertTrue(any(_DOMAIN in args for args in logged))

    def test_already_parsed_object_body_is_dropped_before_the_lease(self):
        task = json.loads(self._payload())
        task["body"] = {"jobs": []}  # a producer that already parsed it
        payload = json.dumps(task).encode("utf-8")
        result = self.worker.process_task(payload, "discovery_learning_tasks")
        self.assertIs(result, False)
        self.mock_redis.set.assert_not_called()

    def test_body_parsing_to_a_scalar_is_dropped(self):
        payload = self._payload(body="42")
        result = self.worker.process_task(payload, "discovery_learning_tasks")
        self.assertIs(result, False)
        self.mock_redis.set.assert_not_called()

    # Proofs 3 and 4: kind bound once and read by both call sites

    def test_has_existing_pr_receives_kind_mapping(self):
        self._run_green()
        self.assertEqual(
            self.mock_publisher.has_existing_pr.call_args.kwargs["kind"], "mapping"
        )

    def test_publish_receives_kind_mapping(self):
        self._run_green()
        self.assertEqual(
            self.mock_publisher.publish.call_args.kwargs["kind"], "mapping"
        )

    def test_has_existing_pr_and_publish_receive_the_same_kind(self):
        self._run_green()
        self.assertEqual(
            self.mock_publisher.has_existing_pr.call_args.kwargs["kind"],
            self.mock_publisher.publish.call_args.kwargs["kind"],
        )

    # Proof 5: staged_paths receives the mapping kind

    def test_publish_receives_the_three_mapping_paths(self):
        self._run_green()
        kwargs = self.mock_publisher.publish.call_args.kwargs
        self.assertEqual(
            kwargs["paths"],
            [
                f"adapters/adapters/mappings/{_NAMES.basename}.json",
                f"adapters/adapters/{_NAMES.basename}_test.py",
                f"adapters/adapters/fixtures/{_NAMES.basename}",
            ],
        )

    def test_publish_receives_mapping_type_as_adapter_type(self):
        self._run_green()
        self.assertEqual(
            self.mock_publisher.publish.call_args.kwargs["adapter_type"], "index"
        )

    # Proof 9: the mapping path's own LLMModel construction

    @patch("llm.learning_task.LLMModel")
    def test_llm_model_receives_index_num_ctx(self, mock_llm_cls):
        self.mock_redis.set.return_value = True
        self.worker._run_adapter_tests = MagicMock(return_value=(True, "PASSED"))
        with (
            patch(
                "llm.learning_task.learn_mapping",
                return_value=(_NAMES, "acme-test-model"),
            ),
            patch.dict(os.environ, {"INDEX_NUM_CTX": "12345"}),
        ):
            self.worker.process_task(self._payload(), "discovery_learning_tasks")
        self.assertEqual(mock_llm_cls.call_args.kwargs["num_ctx"], 12345)

    # Proof 11: lease_type read at every lease site

    def test_green_run_releases_the_index_lease(self):
        self._run_green()
        self.mock_redis.delete.assert_called_with(
            f"LEARNING_IN_PROGRESS:index:{_DOMAIN}"
        )

    def test_only_the_index_lease_marker_is_written(self):
        self._run_green()
        set_keys = {call.args[0] for call in self.mock_redis.set.call_args_list}
        self.assertEqual(set_keys, {f"LEARNING_IN_PROGRESS:index:{_DOMAIN}"})

    # learn_mapping receives the parsed document, never a raw string

    def test_learn_mapping_receives_the_parsed_document(self):
        _, mock_learn = self._run_green()
        _model, domain, url, document, mapping_type = mock_learn.call_args.args
        self.assertEqual(domain, _DOMAIN)
        self.assertEqual(url, _URL)
        self.assertEqual(document, _DOCUMENT)
        self.assertEqual(mapping_type, "index")

    # The two learning-flow exceptions, shared with the adapter path

    @patch("llm.learning_task.logger")
    def test_unlearnable_page_names_the_artifact_and_holds_the_lease(self, mock_logger):
        self.mock_redis.set.return_value = True
        exc = UnlearnablePage("truth agent grounded no job links")
        with patch("llm.learning_task.learn_mapping", side_effect=exc):
            result = self.worker.process_task(
                self._payload(), "discovery_learning_tasks"
            )
        self.assertIs(result, False)
        self.mock_redis.delete.assert_not_called()
        mock_logger.error.assert_called_once_with(
            "Learned nothing for domain=%s url=%s artifact=%s mapping_type=%s: %s",
            _DOMAIN,
            _URL,
            "mapping",
            "index",
            exc,
        )

    @patch("llm.learning_task.logger")
    def test_truth_agent_unreadable_requeues_and_releases_the_index_lease(
        self, mock_logger
    ):
        self.mock_redis.set.return_value = True
        exc = TruthAgentUnreadable("truth agent reply could not be parsed")
        payload = self._payload()
        with patch("llm.learning_task.learn_mapping", side_effect=exc):
            result = self.worker.process_task(payload, "discovery_learning_tasks")
        self.assertIs(result, True)
        self.mock_redis.lpush.assert_called_once_with(
            "discovery_learning_tasks", payload
        )
        self.mock_redis.delete.assert_called_once_with(
            f"LEARNING_IN_PROGRESS:index:{_DOMAIN}"
        )
        mock_logger.error.assert_called_once_with(
            "Truth agent reply unreadable for domain=%s url=%s artifact=%s"
            " mapping_type=%s: %s",
            _DOMAIN,
            _URL,
            "mapping",
            "index",
            exc,
        )

    # Shared has_existing_pr plumbing, exercised through the mapping path

    def test_existing_pr_skips_generation_and_releases_the_lease(self):
        self.mock_redis.set.return_value = True
        self.mock_publisher.has_existing_pr.return_value = True
        with patch("llm.learning_task.learn_mapping") as mock_learn:
            result = self.worker.process_task(
                self._payload(), "discovery_learning_tasks"
            )
        self.assertIs(result, False)
        mock_learn.assert_not_called()
        self.mock_publisher.publish.assert_not_called()
        self.mock_redis.delete.assert_called_once_with(
            f"LEARNING_IN_PROGRESS:index:{_DOMAIN}"
        )

    def test_unknown_pr_state_requeues_without_generating(self):
        self.mock_redis.set.return_value = True
        self.mock_publisher.has_existing_pr.return_value = None
        payload = self._payload()
        with patch("llm.learning_task.learn_mapping") as mock_learn:
            result = self.worker.process_task(payload, "discovery_learning_tasks")
        self.assertIs(result, True)
        mock_learn.assert_not_called()
        self.mock_redis.lpush.assert_called_once_with(
            "discovery_learning_tasks", payload
        )


class TestProcessDetailMappingTask(unittest.TestCase):
    """A mapping task on ``extraction_learning_tasks`` learns a detail mapping."""

    def setUp(self):
        self.mock_redis = MagicMock()
        self.mock_publisher = MagicMock()
        self.mock_publisher.publish.return_value = "https://github.com/acme/repo/pull/9"
        self.mock_publisher.has_existing_pr.return_value = False
        with patch("redis.Redis", return_value=self.mock_redis):
            self.worker = LLMWorker(
                redis_host="localhost",
                redis_port=6379,
                publisher=self.mock_publisher,
            )

    def _payload(self, **overrides) -> bytes:
        task = {
            "artifact": "mapping",
            "domain": _DOMAIN,
            "url": _URL,
            "body": json.dumps(_DOCUMENT),
        }
        task.update(overrides)
        return json.dumps(task).encode("utf-8")

    def _run_green(self):
        self.mock_redis.set.return_value = True
        self.worker._run_adapter_tests = MagicMock(return_value=(True, "PASSED"))
        with patch(
            "llm.learning_task.learn_mapping",
            return_value=(_DETAIL_NAMES, "acme-test-model"),
        ) as mock_learn:
            result = self.worker.process_task(
                self._payload(), "extraction_learning_tasks"
            )
        return result, mock_learn

    # W1
    def test_detail_task_reaches_learn_mapping_and_publish_with_detail_type(self):
        _, mock_learn = self._run_green()
        self.assertEqual(mock_learn.call_args.args[4], "detail")
        kwargs = self.mock_publisher.publish.call_args.kwargs
        self.assertEqual(kwargs["adapter_type"], "detail")
        self.assertEqual(kwargs["kind"], "mapping")
        self.assertEqual(
            kwargs["paths"], staged_paths(_DETAIL_NAMES.basename, "mapping")
        )

    # W2
    def test_only_the_detail_lease_marker_is_written_and_released(self):
        self._run_green()
        set_keys = {call.args[0] for call in self.mock_redis.set.call_args_list}
        self.assertEqual(set_keys, {f"LEARNING_IN_PROGRESS:detail:{_DOMAIN}"})
        self.mock_redis.delete.assert_called_with(
            f"LEARNING_IN_PROGRESS:detail:{_DOMAIN}"
        )

    # W3
    @patch("llm.learning_task.LLMModel")
    def test_llm_model_receives_extraction_num_ctx(self, mock_llm_cls):
        self.mock_redis.set.return_value = True
        self.worker._run_adapter_tests = MagicMock(return_value=(True, "PASSED"))
        with (
            patch(
                "llm.learning_task.learn_mapping",
                return_value=(_DETAIL_NAMES, "acme-test-model"),
            ),
            patch.dict(os.environ, {"EXTRACTION_NUM_CTX": "12345"}, clear=False),
        ):
            os.environ.pop("INDEX_NUM_CTX", None)
            self.worker.process_task(self._payload(), "extraction_learning_tasks")
        self.assertEqual(mock_llm_cls.call_args.kwargs["num_ctx"], 12345)

    # W4
    def test_non_positive_detail_budget_drops_without_lease_or_requeue(self):
        payload = self._payload()
        with (
            patch("llm.learning_task.logger") as mock_logger,
            patch.dict(os.environ, {"EXTRACTION_NUM_CTX": "2000"}, clear=False),
        ):
            os.environ.pop("INDEX_NUM_CTX", None)
            result = self.worker.process_task(payload, "extraction_learning_tasks")
        self.assertIs(result, False)
        self.mock_redis.set.assert_not_called()
        self.mock_redis.lpush.assert_not_called()
        logged = [call.args for call in mock_logger.error.call_args_list]
        self.assertTrue(any("EXTRACTION_NUM_CTX" in args for args in logged))

    # W5
    def test_unknown_queue_is_dropped_without_a_lease(self):
        payload = self._payload()
        result = self.worker.process_task(payload, "some_other_queue")
        self.assertIs(result, False)
        self.mock_redis.set.assert_not_called()

    # W6, first half
    @patch("llm.learning_task.logger")
    def test_unlearnable_page_on_detail_holds_the_lease(self, mock_logger):
        self.mock_redis.set.return_value = True
        exc = UnlearnablePage("truth agent grounded no title, company or description")
        with patch("llm.learning_task.learn_mapping", side_effect=exc):
            result = self.worker.process_task(
                self._payload(), "extraction_learning_tasks"
            )
        self.assertIs(result, False)
        self.mock_redis.delete.assert_not_called()
        mock_logger.error.assert_called_once_with(
            "Learned nothing for domain=%s url=%s artifact=%s mapping_type=%s: %s",
            _DOMAIN,
            _URL,
            "mapping",
            "detail",
            exc,
        )

    # W6, second half
    def test_truth_agent_unreadable_on_detail_releases_and_requeues(self):
        self.mock_redis.set.return_value = True
        exc = TruthAgentUnreadable("truth agent reply could not be parsed")
        payload = self._payload()
        with patch("llm.learning_task.learn_mapping", side_effect=exc):
            result = self.worker.process_task(payload, "extraction_learning_tasks")
        self.assertIs(result, True)
        self.mock_redis.lpush.assert_called_once_with(
            "extraction_learning_tasks", payload
        )
        self.mock_redis.delete.assert_called_once_with(
            f"LEARNING_IN_PROGRESS:detail:{_DOMAIN}"
        )


if __name__ == "__main__":
    unittest.main()
