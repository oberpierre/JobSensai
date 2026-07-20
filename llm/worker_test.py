import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from llm.worker import (
    LLMWorker,
    _adapter_names,
    _domain_slug,
    _parse_json_object,
)


class TestLLMWorker(unittest.TestCase):
    def setUp(self):
        self.mock_redis = MagicMock()
        with patch("redis.Redis", return_value=self.mock_redis):
            self.worker = LLMWorker(redis_host="localhost", redis_port=6379)

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

    def test_complete_learning(self):
        self.worker.complete_learning("google.com", "extraction")
        self.mock_redis.delete.assert_called_with(
            "LEARNING_IN_PROGRESS:extraction:google.com"
        )
        self.mock_redis.set.assert_called_with(
            "LEARNING_COMPLETE:extraction:google.com", "1"
        )

    def test_process_task_discovery_routes_to_snapshot_flow(self):
        self.mock_redis.set.return_value = True

        # Orchestration only: the discovery flow generates then runs the suite once.
        self.worker._learn_discovery = MagicMock()
        self.worker._run_adapter_tests = MagicMock(return_value=True)
        self.worker.complete_learning = MagicMock()

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
        self.worker.complete_learning.assert_called_once_with(
            "newboard.com", "discovery"
        )

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
        with patch("redis.Redis", return_value=MagicMock()):
            worker = LLMWorker()

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.worker._ADAPTERS_DIR", Path(tmp)),
        ):
            names = worker._learn_extraction(
                "acme.com",
                "https://acme.com/job/1",
                "<html><body><h1>Staff Engineer</h1></body></html>",
            )
            fixtures = Path(tmp) / "fixtures" / names.basename
            expected = json.loads((fixtures / "expected.json").read_text())
            detail_html = (fixtures / "detail.html").read_text()
            test_src = (Path(tmp) / f"{names.basename}_test.py").read_text()
            adapter_written = (Path(tmp) / f"{names.basename}.py").exists()

        self.assertEqual(names.basename, "acme_com_extraction_v1")
        self.assertEqual(expected["url"], "https://acme.com/job/1")
        self.assertEqual(expected["title"], "Staff Engineer")
        self.assertIn("ExtractionSnapshotTest", test_src)
        self.assertIn("AcmeComExtractionAdapter", test_src)

        # The truth agent reads the cleaned detail page, and it is stored verbatim.
        self.assertIn("Staff Engineer", detail_html)
        self.assertEqual(llm.generate_expected.call_args.args[0], "extraction")
        self.assertIn("Staff Engineer", llm.generate_expected.call_args.args[1])

        # This slice snapshots only; the code agent that writes the adapter comes next.
        self.assertFalse(adapter_written)


if __name__ == "__main__":
    unittest.main()
