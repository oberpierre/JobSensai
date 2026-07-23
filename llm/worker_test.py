import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from llm.worker import (
    LLMWorker,
    _adapter_names,
    _domain_slug,
    _parse_json_object,
    _worker_from_env,
)


class TestLLMWorker(unittest.TestCase):
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

    def test_release_learning_drops_the_lease_and_records_nothing(self):
        self.worker.release_learning("google.com", "extraction")
        self.mock_redis.delete.assert_called_with(
            "LEARNING_IN_PROGRESS:extraction:google.com"
        )
        self.assertEqual(self.mock_redis.set.call_count, 0)

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
        self.worker.process_task(task_payload, "extraction_learning_tasks")

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

    def test_unknown_pr_state_fails_closed(self):
        """A wrong skip costs one crawl; a wrong re-learn costs a GPU run."""
        self.mock_publisher.has_existing_pr.return_value = None
        self._run_extraction_task(passed=True)

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


class TestDomainSlug(unittest.TestCase):
    def test_simple_domain(self):
        self.assertEqual(_domain_slug("www.google.com"), "www_google_com")

    def test_hyphenated_domain_is_a_valid_module_name(self):
        slug = _domain_slug("job-boards.greenhouse.io")
        self.assertEqual(slug, "job_boards_greenhouse_io")
        # The basename derived from the slug must import cleanly.
        self.assertTrue(f"{slug}_discovery_v1".isidentifier())

    def test_uppercase_is_normalised(self):
        self.assertEqual(_domain_slug("Google.COM"), "google_com")

    def test_no_leading_or_trailing_underscores(self):
        self.assertEqual(_domain_slug(".weird..domain."), "weird_domain")


class TestAdapterNames(unittest.TestCase):
    def test_simple_discovery(self):
        names = _adapter_names("google.com", "discovery")
        self.assertEqual(names.basename, "google_com_discovery_v1")
        self.assertEqual(names.adapter_class, "GoogleComDiscoveryAdapter")
        self.assertEqual(names.test_class, "TestGoogleComDiscoveryAdapter")
        self.assertEqual(names.module_path, f"adapters.adapters.{names.basename}")

    def test_hyphenated_extraction_with_version(self):
        names = _adapter_names("job-boards.greenhouse.io", "extraction", version=2)
        self.assertEqual(names.basename, "job_boards_greenhouse_io_extraction_v2")
        self.assertEqual(names.adapter_class, "JobBoardsGreenhouseIoExtractionAdapter")

    def test_names_are_valid_python_identifiers(self):
        names = _adapter_names("job-boards.greenhouse.io", "discovery")
        self.assertTrue(names.basename.isidentifier())
        self.assertTrue(names.adapter_class.isidentifier())
        self.assertTrue(names.test_class.isidentifier())


class TestParseJsonObject(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(_parse_json_object('{"a": 1}'), {"a": 1})

    def test_json_wrapped_in_fence_and_prose(self):
        raw = 'Here you go:\n```json\n{"a": 1}\n```'
        self.assertEqual(_parse_json_object(raw), {"a": 1})

    def test_non_object_returns_empty(self):
        self.assertEqual(_parse_json_object("not json at all"), {})
        self.assertEqual(_parse_json_object("[1, 2]"), {})


class TestLearnDiscovery(unittest.TestCase):
    @patch("llm.worker.LLMModel")
    def test_writes_snapshot_test_and_adapter(self, mock_llm_cls):
        llm = mock_llm_cls.return_value
        llm.generate_expected.return_value = json.dumps(
            {
                "job_links": ["https://acme.com/jobs/1"],
                "next_page_links": ["https://acme.com/jobs?page=2"],
            }
        )
        # Wrapped in a markdown fence to prove _strip_code_fences runs.
        llm.generate_code.return_value = (
            "```python\nclass AcmeComDiscoveryAdapter: pass\n```"
        )
        with patch("redis.Redis", return_value=MagicMock()):
            worker = LLMWorker()

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.worker._ADAPTERS_DIR", Path(tmp)),
        ):
            (Path(tmp) / "base.py").write_text("class DiscoveryAdapter: pass\n")
            names = worker._learn_discovery(
                "acme.com",
                "https://acme.com/jobs",
                "<html><body>"
                "<div class='jobs'><a href='/jobs/1'>Job</a></div>"
                "<div class='filler'><p>prose, no links</p></div>"
                "</body></html>",
            )
            fixtures = Path(tmp) / "fixtures" / names.basename
            expected = json.loads((fixtures / "expected.json").read_text())
            index_html = (fixtures / "index.html").read_text()
            test_src = (Path(tmp) / f"{names.basename}_test.py").read_text()
            adapter_src = (Path(tmp) / f"{names.basename}.py").read_text()

        # Discovery runs on the pruned skeleton, so the smaller context window suffices.
        self.assertEqual(mock_llm_cls.call_args.kwargs["num_ctx"], 32768)
        self.assertEqual(names.basename, "acme_com_discovery_v1")
        self.assertEqual(expected["job_links"], ["https://acme.com/jobs/1"])
        self.assertIn("DiscoverySnapshotTest", test_src)
        self.assertIn("AcmeComDiscoveryAdapter", test_src)
        # The code fence was stripped from the written adapter source.
        self.assertEqual(adapter_src.strip(), "class AcmeComDiscoveryAdapter: pass")

        # index.html keeps the full page; both agents saw only the pruned skeleton.
        self.assertIn("prose, no links", index_html)
        lean_truth = llm.generate_expected.call_args.args[1]
        lean_code = llm.generate_code.call_args.args[1]
        self.assertNotIn("prose, no links", lean_truth)
        self.assertNotIn("prose, no links", lean_code)
        self.assertIn("/jobs/1", lean_code)


class TestLearnExtraction(unittest.TestCase):
    @patch("llm.worker.LLMModel")
    def test_writes_detail_fixture_and_snapshot_test(self, mock_llm_cls):
        llm = mock_llm_cls.return_value
        llm.generate_expected.return_value = json.dumps(
            {
                "title": "Staff Engineer",
                "company_name": "Acme",
                "employment_type": "Full-time",
                "locations": ["Remote"],
                "categories": ["Engineering"],
                "description": "We build things.",
                "metadata": {},
            }
        )
        # Wrapped in a fence to prove _strip_code_fences runs on the adapter source.
        llm.generate_code.return_value = (
            "```python\nclass AcmeComExtractionAdapter: pass\n```"
        )
        with patch("redis.Redis", return_value=MagicMock()):
            worker = LLMWorker()

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.worker._ADAPTERS_DIR", Path(tmp)),
        ):
            (Path(tmp) / "base.py").write_text("class ExtractionAdapter: pass\n")
            names = worker._learn_extraction(
                "acme.com",
                "https://acme.com/job/1",
                "<html><body><h1>Staff Engineer</h1></body></html>",
            )
            fixtures = Path(tmp) / "fixtures" / names.basename
            expected = json.loads((fixtures / "expected.json").read_text())
            detail_html = (fixtures / "detail.html").read_text()
            test_src = (Path(tmp) / f"{names.basename}_test.py").read_text()
            adapter_src = (Path(tmp) / f"{names.basename}.py").read_text()

        # Detail bodies are large, so extraction gets the wider context window.
        self.assertEqual(mock_llm_cls.call_args.kwargs["num_ctx"], 65536)
        self.assertEqual(names.basename, "acme_com_extraction_v1")
        self.assertEqual(expected["url"], "https://acme.com/job/1")
        self.assertEqual(expected["title"], "Staff Engineer")
        self.assertIn("ExtractionSnapshotTest", test_src)
        self.assertIn("AcmeComExtractionAdapter", test_src)
        # The code fence was stripped from the written adapter source.
        self.assertEqual(adapter_src.strip(), "class AcmeComExtractionAdapter: pass")

        # Truth and code agents both read the cleaned detail page (never pruned).
        self.assertIn("Staff Engineer", detail_html)
        self.assertEqual(llm.generate_expected.call_args.args[0], "extraction")
        self.assertIn("Staff Engineer", llm.generate_expected.call_args.args[1])
        self.assertEqual(llm.generate_code.call_args.args[0], "extraction")
        self.assertIn("Staff Engineer", llm.generate_code.call_args.args[1])


class TestWorkerFromEnv(unittest.TestCase):
    @patch("llm.worker.redis.Redis")
    def test_reads_ollama_and_redis_from_env(self, mock_redis):
        env = {
            "OLLAMA_HOST": "http://127.0.0.1",
            "OLLAMA_PORT": "9999",
            "REDIS_HOST": "cluster-redis",
            "REDIS_PORT": "6380",
        }
        with patch.dict(os.environ, env):
            worker = _worker_from_env()

        self.assertEqual(worker.llm_url, "http://http://127.0.0.1:9999")
        mock_redis.assert_called_once_with(host="cluster-redis", port=6380)

    @patch("llm.worker.redis.Redis")
    def test_falls_back_to_localhost_defaults(self, mock_redis):
        with patch.dict(os.environ, {}, clear=True):
            worker = _worker_from_env()

        self.assertEqual(worker.llm_url, "http://localhost:11434")
        mock_redis.assert_called_once_with(host="localhost", port=6379)


if __name__ == "__main__":
    unittest.main()
