import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from llm.worker import LLMWorker, UnlearnablePage, _parse_json_object


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
        llm.model_name = "acme-test-model"
        with patch("redis.Redis", return_value=MagicMock()):
            worker = LLMWorker()

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            (Path(tmp) / "base.py").write_text("class DiscoveryAdapter: pass\n")
            names, model_name = worker._learn_discovery(
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
        # The model that ran travels out alongside the names it generated.
        self.assertEqual(model_name, "acme-test-model")
        self.assertEqual(names.basename, "acme_com_discovery_v1")
        self.assertEqual(expected["job_links"], ["https://acme.com/jobs/1"])
        self.assertIn("DiscoverySnapshotTest", test_src)
        self.assertIn("AcmeComDiscoveryAdapter", test_src)
        # The code fence was stripped from the written adapter source.
        self.assertEqual(adapter_src.strip(), "class AcmeComDiscoveryAdapter: pass")

        # index.html keeps the full page, whereas both agents saw only the
        # pruned skeleton.
        self.assertIn("prose, no links", index_html)
        lean_truth = llm.generate_expected.call_args.args[1]
        lean_code = llm.generate_code.call_args.args[1]
        self.assertNotIn("prose, no links", lean_truth)
        self.assertNotIn("prose, no links", lean_code)
        self.assertIn("/jobs/1", lean_code)


class TestLearnDiscoveryUnlearnable(unittest.TestCase):
    @patch("llm.worker.LLMModel")
    def test_empty_job_links_raises_before_writing_anything(self, mock_llm_cls):
        llm = mock_llm_cls.return_value
        llm.generate_expected.return_value = json.dumps(
            {"job_links": [], "next_page_links": []}
        )
        with patch("redis.Redis", return_value=MagicMock()):
            worker = LLMWorker()

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            with self.assertRaises(UnlearnablePage):
                worker._learn_discovery(
                    "acme.com",
                    "https://acme.com/jobs",
                    "<html><body>no anchors here</body></html>",
                )
            self.assertEqual(list(Path(tmp).iterdir()), [])
        llm.generate_code.assert_not_called()


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
        llm.model_name = "acme-test-model"
        with patch("redis.Redis", return_value=MagicMock()):
            worker = LLMWorker()

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            (Path(tmp) / "base.py").write_text("class ExtractionAdapter: pass\n")
            names, model_name = worker._learn_extraction(
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
        # The model that ran travels out alongside the names it generated.
        self.assertEqual(model_name, "acme-test-model")
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


class TestLearnExtractionUnlearnable(unittest.TestCase):
    def _assert_raises_and_writes_nothing(self, mock_llm_cls, truth: dict):
        llm = mock_llm_cls.return_value
        llm.generate_expected.return_value = json.dumps(truth)
        with patch("redis.Redis", return_value=MagicMock()):
            worker = LLMWorker()

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            with self.assertRaises(UnlearnablePage):
                worker._learn_extraction(
                    "acme.com",
                    "https://acme.com/job/1",
                    "<html><body>no posting content</body></html>",
                )
            self.assertEqual(list(Path(tmp).iterdir()), [])
        llm.generate_code.assert_not_called()

    @patch("llm.worker.LLMModel")
    def test_absent_title_and_description_raises_before_writing_anything(
        self, mock_llm_cls
    ):
        self._assert_raises_and_writes_nothing(
            mock_llm_cls, {"company_name": "Acme", "locations": ["Remote"]}
        )

    @patch("llm.worker.LLMModel")
    def test_blank_title_and_description_raises_before_writing_anything(
        self, mock_llm_cls
    ):
        self._assert_raises_and_writes_nothing(
            mock_llm_cls, {"title": "  ", "description": ""}
        )


if __name__ == "__main__":
    unittest.main()
