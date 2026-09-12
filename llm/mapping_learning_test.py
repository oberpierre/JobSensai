import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from llm.learning_errors import TruthAgentUnreadable, UnlearnablePage
from llm.mapping_learning import _trim_to_budget, budget_chars, learn_mapping


class TestBudgetChars(unittest.TestCase):
    def test_default_window(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INDEX_NUM_CTX", None)
            # (65536 - 4096) * 2, the default the ADR names.
            self.assertEqual(budget_chars(), 122880)

    def test_custom_window(self):
        with patch.dict(os.environ, {"INDEX_NUM_CTX": "8192"}):
            self.assertEqual(budget_chars(), (8192 - 4096) * 2)


class TestTrimToBudget(unittest.TestCase):
    def test_already_within_budget_returns_unchanged(self):
        document = {"jobs": [{"id": 1}, {"id": 2}]}
        trimmed, text = _trim_to_budget(document, 10_000)
        self.assertEqual(trimmed, document)
        self.assertEqual(text, json.dumps(document, indent=2))

    def test_drops_from_the_largest_array(self):
        document = {
            "jobs": [{"id": i, "pad": "A" * 10} for i in range(20)],
            "offices": [{"name": "Zurich"}, {"name": "Remote"}],
        }
        trimmed, text = _trim_to_budget(document, 400)
        self.assertLess(len(trimmed["jobs"]), 20)
        # The smaller array is untouched: only the longest array is ever dropped.
        self.assertEqual(len(trimmed["offices"]), 2)
        self.assertLessEqual(len(text), 400)

    def test_refuses_when_only_singleton_arrays_remain(self):
        document = {"a": [1], "b": [2]}
        with self.assertRaises(UnlearnablePage):
            _trim_to_budget(document, 1)

    def test_refuses_when_document_has_no_arrays(self):
        document = {"a": "x" * 1000}
        with self.assertRaises(UnlearnablePage):
            _trim_to_budget(document, 1)

    def test_does_not_mutate_the_callers_document(self):
        document = {"jobs": [{"id": i} for i in range(20)]}
        _trim_to_budget(document, 50)
        self.assertEqual(len(document["jobs"]), 20)


def _stub_model(job_links: list, jmespath_reply: dict | str) -> MagicMock:
    model = MagicMock()
    model.model_name = "acme-test-model"
    model.generate_mapping_expected.return_value = json.dumps({"job_links": job_links})
    model.generate_mapping.return_value = (
        jmespath_reply
        if isinstance(jmespath_reply, str)
        else json.dumps(jmespath_reply)
    )
    return model


class TestLearnMapping(unittest.TestCase):
    def test_writes_index_fixture_and_snapshot_test(self):
        model = _stub_model(
            ["https://acme.com/jobs/1"],
            {"jmespath": {"postings": "jobs[]", "job_url": "absolute_url"}},
        )
        document = {"jobs": [{"id": 1, "absolute_url": "https://acme.com/jobs/1"}]}

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            names, model_name = learn_mapping(
                model, "acme.com", "https://acme.com/api/jobs", document, "index"
            )
            fixtures = Path(tmp) / "fixtures" / names.basename
            expected = json.loads((fixtures / "expected.json").read_text())
            index_json = json.loads((fixtures / "index.json").read_text())
            test_src = (Path(tmp) / f"{names.basename}_test.py").read_text()
            mapping_doc = json.loads(
                (Path(tmp) / "mappings" / f"{names.basename}.json").read_text()
            )

        self.assertEqual(model_name, "acme-test-model")
        self.assertEqual(names.basename, "acme_com_index_v1")
        self.assertEqual(expected["job_links"], ["https://acme.com/jobs/1"])
        self.assertEqual(expected["url"], "https://acme.com/api/jobs")
        self.assertEqual(index_json, document)
        self.assertIn("IndexMappingSnapshotTest", test_src)
        self.assertIn(names.basename, test_src)
        self.assertEqual(mapping_doc["version"], 1)
        self.assertEqual(mapping_doc["type"], "index")
        self.assertEqual(mapping_doc["domains"], ["acme.com"])
        self.assertEqual(mapping_doc["jmespath"]["postings"], "jobs[]")

    def test_orchestrator_overrides_the_models_domains(self):
        # A model that invents a hostname must not route the document there:
        # version/type/domains are the orchestrator's, written over the reply.
        model = _stub_model(
            ["https://acme.com/jobs/1"],
            {
                "jmespath": {"postings": "jobs[]", "job_url": "absolute_url"},
                "version": 99,
                "type": "detail",
                "domains": ["evil.example"],
            },
        )
        document = {"jobs": [{"id": 1, "absolute_url": "https://acme.com/jobs/1"}]}

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            names, _ = learn_mapping(
                model, "acme.com", "https://acme.com/api/jobs", document, "index"
            )
            mapping_doc = json.loads(
                (Path(tmp) / "mappings" / f"{names.basename}.json").read_text()
            )

        self.assertEqual(mapping_doc["domains"], ["acme.com"])
        self.assertEqual(mapping_doc["version"], 1)
        self.assertEqual(mapping_doc["type"], "index")

    def test_budget_is_cut_once_and_shared_by_both_agents(self):
        model = _stub_model(
            ["https://acme.com/jobs/1"],
            {"jmespath": {"postings": "jobs[]", "job_url": "absolute_url"}},
        )
        document = {
            "jobs": [
                {"id": i, "absolute_url": f"https://acme.com/jobs/{i}", "pad": "A" * 40}
                for i in range(200)
            ]
        }

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
            patch.dict(os.environ, {"INDEX_NUM_CTX": "4608"}),  # budget = 1024 chars
        ):
            learn_mapping(
                model, "acme.com", "https://acme.com/api/jobs", document, "index"
            )

        truth_body = model.generate_mapping_expected.call_args.args[1]
        code_body = model.generate_mapping.call_args.args[1]
        self.assertEqual(truth_body, code_body)
        self.assertLessEqual(len(truth_body), 1024)

    def test_written_index_fixture_is_within_the_budget(self):
        # Differential proof: a trimmer that returns the document untouched would
        # still pass every other case here, so this grades the artifact directly.
        model = _stub_model(
            ["https://acme.com/jobs/1"],
            {"jmespath": {"postings": "jobs[]", "job_url": "absolute_url"}},
        )
        document = {
            "jobs": [
                {"id": i, "absolute_url": f"https://acme.com/jobs/{i}", "pad": "A" * 40}
                for i in range(200)
            ]
        }

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
            patch.dict(os.environ, {"INDEX_NUM_CTX": "4608"}),  # budget = 1024 chars
        ):
            names, _ = learn_mapping(
                model, "acme.com", "https://acme.com/api/jobs", document, "index"
            )
            fixtures = Path(tmp) / "fixtures" / names.basename
            index_text = (fixtures / "index.json").read_text()

        self.assertLessEqual(len(index_text), 1024)


class TestLearnMappingTruthAgentUnreadable(unittest.TestCase):
    def test_unparseable_reply_raises_before_writing_anything(self):
        model = MagicMock()
        model.generate_mapping_expected.return_value = "the model rambled"
        document = {"jobs": [{"id": 1}]}

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            with self.assertRaises(TruthAgentUnreadable):
                learn_mapping(
                    model, "acme.com", "https://acme.com/api/jobs", document, "index"
                )
            self.assertEqual(list(Path(tmp).iterdir()), [])
        model.generate_mapping.assert_not_called()


class TestLearnMappingUnlearnablePage(unittest.TestCase):
    def test_empty_job_links_raises_before_writing_anything(self):
        model = _stub_model([], {"jmespath": {}})
        document = {"jobs": []}

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            with self.assertRaises(UnlearnablePage):
                learn_mapping(
                    model, "acme.com", "https://acme.com/api/jobs", document, "index"
                )
            self.assertEqual(list(Path(tmp).iterdir()), [])
        model.generate_mapping.assert_not_called()


class TestLearnMappingUnreadableCodeReply(unittest.TestCase):
    def test_unreadable_code_reply_is_written_verbatim(self):
        model = _stub_model(["https://acme.com/jobs/1"], "not json at all")
        document = {"jobs": [{"id": 1, "absolute_url": "https://acme.com/jobs/1"}]}

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            names, _ = learn_mapping(
                model, "acme.com", "https://acme.com/api/jobs", document, "index"
            )
            written = (Path(tmp) / "mappings" / f"{names.basename}.json").read_text()

        self.assertEqual(written, "not json at all")


class TestLearnMappingArtifactSet(unittest.TestCase):
    """Grades the artifact set rather than a writer: every other case in this
    module mutates a value, so a template naming `fixture_dir` instead of
    `basename`, or a writer that skips creating `mappings/`, would satisfy all
    of them and reach production as a board whose learned mapping is a draft
    pull request forever."""

    def _generated_suite_result(self, jmespath_block: dict) -> unittest.TestResult:
        model = _stub_model(["https://acme.com/jobs/1"], {"jmespath": jmespath_block})
        document = {"jobs": [{"id": 1, "absolute_url": "https://acme.com/jobs/1"}]}

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            names, _ = learn_mapping(
                model, "acme.com", "https://acme.com/api/jobs", document, "index"
            )
            test_path = Path(tmp) / f"{names.basename}_test.py"
            module_name = f"generated_{names.basename}_test"
            spec = importlib.util.spec_from_file_location(module_name, test_path)
            module = importlib.util.module_from_spec(spec)
            # Registered before exec: IndexMappingSnapshotTest resolves its
            # fixture directory with inspect.getfile(type(self)), which raises
            # for a class whose module was never registered in sys.modules.
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
                test_class = getattr(module, names.test_class)
                suite = unittest.TestLoader().loadTestsFromTestCase(test_class)
                result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
            finally:
                del sys.modules[module_name]
        return result

    def test_generated_suite_passes_for_a_correct_mapping(self):
        result = self._generated_suite_result(
            {"postings": "jobs[]", "job_url": "absolute_url"}
        )
        self.assertTrue(result.wasSuccessful())

    def test_generated_suite_fails_for_an_unknown_jmespath_key(self):
        result = self._generated_suite_result(
            {"postings": "jobs[]", "job_url": "absolute_url", "extra": "nope"}
        )
        self.assertFalse(result.wasSuccessful())


if __name__ == "__main__":
    unittest.main()
