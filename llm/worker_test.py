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

    @patch("llm.worker.LLMModel")
    def test_process_task_full_pipeline(self, mock_llm_class):
        self.mock_redis.set.return_value = True

        mock_llm_instance = mock_llm_class.return_value
        mock_llm_instance.generate_adapter.return_value = (
            "class NewAdapter(DiscoveryAdapter): pass\n"
            "# --- TEST CODE ---\n"
            "def test_new(): pass"
        )

        # Replace sub-methods with mocks so we test orchestration only
        self.worker.parse_llm_response = MagicMock(
            return_value=(
                "class NewAdapter(DiscoveryAdapter): pass",
                "def test_new(): pass",
            )
        )
        self.worker._quick_validate = MagicMock(return_value=True)
        self.worker._write_test_and_verify = MagicMock(return_value=True)
        self.worker._commit = MagicMock()
        self.worker.complete_learning = MagicMock()

        task_payload = json.dumps(
            {"domain": "newboard.com", "html": "<html></html>"}
        ).encode("utf-8")
        self.worker.process_task(task_payload, "discovery_learning_tasks")

        self.worker._write_test_and_verify.assert_called_once()
        self.worker.complete_learning.assert_called_once_with(
            "newboard.com", "discovery"
        )

    def test_parse_llm_response_with_separator(self):
        response = "adapter code\n# --- TEST CODE ---\ntest code"
        adapter, test = self.worker.parse_llm_response(response)
        self.assertEqual(adapter, "adapter code")
        self.assertEqual(test, "test code")

    def test_parse_llm_response_without_separator(self):
        response = "adapter code only"
        adapter, test = self.worker.parse_llm_response(response)
        self.assertEqual(adapter, "adapter code only")
        self.assertIsNone(test)

    def test_parse_llm_response_empty_parts_become_none(self):
        response = "# --- TEST CODE ---"
        adapter, test = self.worker.parse_llm_response(response)
        self.assertIsNone(adapter)
        self.assertIsNone(test)

    def test_validate_code_discovery_success(self):
        adapter_code = (
            "from adapters.adapters.base import DiscoveryAdapter\n"
            "class NewAdapter(DiscoveryAdapter):\n"
            "    def get_job_links(self, html, url): return []\n"
            "    def get_next_page_links(self, html, url): return []\n"
        )
        self.assertTrue(
            self.worker.validate_code(
                "example.com",
                adapter_code,
                None,
                "<html></html>",
                "http://example.com",
                adapter_type="discovery",
            )
        )

    def test_validate_code_extraction_success(self):
        adapter_code = (
            "from adapters.adapters.base import ExtractionAdapter\n"
            "class NewAdapter(ExtractionAdapter):\n"
            "    def extract(self, html, url): return {'title': 'Job'}\n"
        )
        self.assertTrue(
            self.worker.validate_code(
                "example.com",
                adapter_code,
                None,
                "<html></html>",
                "http://example.com",
                adapter_type="extraction",
            )
        )

    def test_validate_code_syntax_error(self):
        self.assertFalse(
            self.worker.validate_code(
                "example.com",
                "class Broken(: invalid",
                None,
                "<html></html>",
                "http://example.com",
            )
        )

    def test_validate_code_wrong_base_class(self):
        adapter_code = "class NewAdapter: pass"
        self.assertFalse(
            self.worker.validate_code(
                "example.com",
                adapter_code,
                None,
                "<html></html>",
                "http://example.com",
            )
        )

    @patch("subprocess.run")
    def test_run_generated_tests_success(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "PASSED"
        self.assertTrue(
            self.worker.run_generated_tests(
                "example.com",
                (
                    "from adapters.adapters.base import DiscoveryAdapter\n"
                    "class A(DiscoveryAdapter): pass"
                ),
                "def test_logic(): assert True",
            )
        )

    @patch("subprocess.run")
    def test_run_generated_tests_failure(self, mock_run):
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = "FAILED"
        self.assertFalse(
            self.worker.run_generated_tests(
                "example.com",
                "class A: pass",
                "def test_logic(): assert False",
            )
        )

    @patch("llm.worker.subprocess.run")
    def test_save_and_commit(self, mock_subproc):
        mock_subproc.return_value.returncode = 0

        with (
            patch.object(self.worker, "_write_adapter_files") as mock_write,
            patch.object(self.worker, "_commit") as mock_commit,
        ):
            self.worker.save_and_commit(
                "example.com", "adapter code", "test code", "extraction"
            )

        mock_write.assert_called_once_with(
            "example.com", "adapter code", "test code", "extraction"
        )
        mock_commit.assert_called_once_with("example.com", "extraction")

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
        self.assertEqual(
            names.adapter_class, "JobBoardsGreenhouseIoExtractionAdapter"
        )

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


class TestWriteDiscoverySnapshot(unittest.TestCase):
    @patch("llm.worker.LLMModel")
    def test_writes_snapshot_and_deterministic_test(self, mock_llm_cls):
        mock_llm_cls.return_value.generate_expected.return_value = json.dumps(
            {
                "job_links": ["https://acme.com/jobs/1"],
                "next_page_links": ["https://acme.com/jobs?page=2"],
            }
        )
        with patch("redis.Redis", return_value=MagicMock()):
            worker = LLMWorker()

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.worker._ADAPTERS_DIR", Path(tmp)),
        ):
            names = worker._write_discovery_snapshot(
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

        self.assertEqual(names.basename, "acme_com_discovery_v1")
        self.assertEqual(expected["url"], "https://acme.com/jobs")
        self.assertEqual(expected["job_links"], ["https://acme.com/jobs/1"])
        self.assertIn("DiscoverySnapshotTest", test_src)
        self.assertIn("AcmeComDiscoveryAdapter", test_src)
        self.assertIn('fixture_dir = "acme_com_discovery_v1"', test_src)

        # index.html keeps the full page (over-selection is caught later against it)...
        self.assertIn("prose, no links", index_html)
        # ...while the truth agent sees only the pruned, link-bearing skeleton.
        call = mock_llm_cls.return_value.generate_expected.call_args
        self.assertEqual(call.args[0], "discovery")
        lean = call.args[1]
        self.assertIn("/jobs/1", lean)
        self.assertNotIn("prose, no links", lean)


if __name__ == "__main__":
    unittest.main()
