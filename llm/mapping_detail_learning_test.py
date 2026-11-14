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
from llm.mapping_learning import learn_mapping

_DOMAIN = "acme.com"
_URL = "https://acme.com/api/jobs/1"
_POSTING = {
    "title": "Engineer",
    "company_name": "Acme",
    "content": "&lt;p&gt;Build things&lt;/p&gt;",
    "offices": [{"name": "Zürich"}],
}
_DEFAULT_JMESPATH = {
    "title": "title",
    "company_name": "company_name",
    "description": "markdown(unescape(content))",
}
_STEP5_MESSAGE = "truth agent grounded no title, company or description"


def _stub_model(truth: dict, jmespath_reply: dict | str) -> MagicMock:
    model = MagicMock()
    model.model_name = "acme-test-model"
    model.generate_mapping_expected.return_value = json.dumps(truth)
    model.generate_mapping.return_value = (
        jmespath_reply
        if isinstance(jmespath_reply, str)
        else json.dumps(jmespath_reply)
    )
    return model


def _learn(
    truth: dict, jmespath_reply: dict | None = None, posting: dict | None = None
):
    """Run learn_mapping for one detail case and return everything it wrote."""
    posting = _POSTING if posting is None else posting
    if jmespath_reply is None:
        jmespath_reply = {"jmespath": dict(_DEFAULT_JMESPATH)}
    model = _stub_model(truth, jmespath_reply)
    with (
        tempfile.TemporaryDirectory() as tmp,
        patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
    ):
        names, model_name = learn_mapping(model, _DOMAIN, _URL, posting, "detail")
        fixtures = Path(tmp) / "fixtures" / names.basename
        detail_text = (fixtures / "detail.json").read_text()
        expected = json.loads((fixtures / "expected.json").read_text())
        test_src = (Path(tmp) / f"{names.basename}_test.py").read_text()
        mapping_doc = json.loads(
            (Path(tmp) / "mappings" / f"{names.basename}.json").read_text()
        )
    return names, model_name, detail_text, expected, test_src, mapping_doc


class TestLearnDetailMappingDescription(unittest.TestCase):
    """D1-D5: where the resolved description comes from."""

    def test_d1_field_source_html_escaped_true(self):
        truth = {
            "title": "Engineer",
            "company_name": "Acme",
            "description_source": {"field": "content", "html_escaped": True},
        }
        names, _, detail_text, expected, test_src, _ = _learn(truth)
        self.assertEqual(detail_text, json.dumps(_POSTING, indent=2))
        self.assertEqual(expected["description"], "Build things")
        self.assertEqual(
            expected["description_source"], {"field": "content", "html_escaped": True}
        )
        self.assertIn("DetailMappingSnapshotTest", test_src)
        self.assertEqual(names.basename, "acme_com_detail_v1")

    def test_d2_field_source_html_escaped_false(self):
        truth = {
            "title": "Engineer",
            "company_name": "Acme",
            "description_source": {"field": "content", "html_escaped": False},
        }
        _, _, _, expected, _, _ = _learn(truth)
        self.assertEqual(expected["description"], "<p>Build things</p>")

    def test_d3_html_escaped_field_is_unescaped_once(self):
        truth = {
            "title": "Engineer",
            "company_name": "Acme",
            "description_source": {"field": "content", "html_escaped": False},
        }
        posting = {**_POSTING, "content": "<p>T&amp;E; review</p>"}
        _, _, _, expected, _, _ = _learn(truth, posting=posting)
        self.assertEqual(expected["description"], "T&E; review")

    def test_d4_source_wins_over_a_transcription(self):
        truth = {
            "title": "Engineer",
            "company_name": "Acme",
            "description_source": {"field": "content", "html_escaped": True},
            "description": "Transcribed.",
        }
        _, _, _, expected, _, _ = _learn(truth)
        self.assertEqual(expected["description"], "Build things")

    def test_d5_transcription_with_no_source(self):
        truth = {
            "title": "Engineer",
            "company_name": "Acme",
            "description": "# Role\n\nBuild things",
        }
        _, _, _, expected, _, _ = _learn(truth)
        self.assertEqual(expected["description"], "# Role\n\nBuild things")
        self.assertNotIn("description_source", expected)


class TestLearnDetailMappingPay(unittest.TestCase):
    def test_d13_truth_pay_reaches_the_snapshot(self):
        pay = {"min": 155000, "max": 205000, "currency": "EUR", "period": "year"}
        truth = {
            "title": "Engineer",
            "company_name": "Acme",
            "pay": pay,
            "description_source": {"field": "content", "html_escaped": True},
        }
        _, _, _, expected, _, _ = _learn(truth)
        self.assertEqual(expected["pay"], pay)


class TestLearnDetailMappingSourceDefects(unittest.TestCase):
    """D6: a description_source the orchestrator cannot use holds the lease."""

    def _assert_defect(self, truth: dict, posting: dict | None = None):
        posting = _POSTING if posting is None else posting
        model = _stub_model(truth, {"jmespath": dict(_DEFAULT_JMESPATH)})
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            with self.assertRaises(UnlearnablePage) as caught:
                learn_mapping(model, _DOMAIN, _URL, posting, "detail")
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertNotEqual(str(caught.exception), _STEP5_MESSAGE)

    def test_d6_source_defects(self):
        base = {"title": "Engineer", "company_name": "Acme"}
        cases = {
            "description_source a string": {**base, "description_source": "content"},
            "field a number": {
                **base,
                "description_source": {"field": 5, "html_escaped": True},
            },
            "field empty": {
                **base,
                "description_source": {"field": "", "html_escaped": True},
            },
            "field whitespace": {
                **base,
                "description_source": {"field": "   ", "html_escaped": True},
            },
            "field does not compile": {
                **base,
                "description_source": {"field": "content[[", "html_escaped": True},
            },
            "field calls markdown/unescape": {
                **base,
                "description_source": {
                    "field": "markdown(unescape(content))",
                    "html_escaped": True,
                },
            },
            "html_escaped a string": {
                **base,
                "description_source": {"field": "content", "html_escaped": "yes"},
            },
            "html_escaped an int": {
                **base,
                "description_source": {"field": "content", "html_escaped": 1},
            },
            "field selects a list": {
                **base,
                "description_source": {"field": "offices", "html_escaped": True},
            },
            "field selects None": {
                **base,
                "description_source": {"field": "missing", "html_escaped": True},
            },
        }
        for label, truth in cases.items():
            with self.subTest(label):
                self._assert_defect(truth)

        with self.subTest("posting content is blank"):
            truth = {
                **base,
                "description_source": {"field": "content", "html_escaped": True},
            }
            self._assert_defect(truth, posting={**_POSTING, "content": "   "})


class TestLearnDetailMappingTruthAgentUnreadable(unittest.TestCase):
    def test_d7_empty_reply_raises_and_writes_nothing(self):
        model = MagicMock()
        model.generate_mapping_expected.return_value = "{}"
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            with self.assertRaises(TruthAgentUnreadable):
                learn_mapping(model, _DOMAIN, _URL, _POSTING, "detail")
            self.assertEqual(list(Path(tmp).iterdir()), [])
        model.generate_mapping.assert_not_called()


class TestLearnDetailMappingGroundingDefects(unittest.TestCase):
    """D8: a reply grounding no title, company or description holds the lease."""

    _BASE = {
        "title": "Engineer",
        "company_name": "Acme",
        "description_source": {"field": "content", "html_escaped": True},
    }

    def _assert_grounds_nothing(self, truth: dict):
        model = _stub_model(truth, {"jmespath": dict(_DEFAULT_JMESPATH)})
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            with self.assertRaises(UnlearnablePage) as caught:
                learn_mapping(model, _DOMAIN, _URL, _POSTING, "detail")
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertEqual(str(caught.exception), _STEP5_MESSAGE)

    def test_d8_blank_title(self):
        self._assert_grounds_nothing({**self._BASE, "title": "   "})

    def test_d8_no_company_name(self):
        truth = dict(self._BASE)
        del truth["company_name"]
        self._assert_grounds_nothing(truth)

    def test_d8_no_description_source_or_description(self):
        truth = dict(self._BASE)
        del truth["description_source"]
        self._assert_grounds_nothing(truth)


class TestLearnDetailMappingBlankRenderedDescription(unittest.TestCase):
    def test_d9_source_rendering_blank_raises_step5_message(self):
        truth = {
            "title": "Engineer",
            "company_name": "Acme",
            "description_source": {"field": "content", "html_escaped": False},
        }
        posting = {**_POSTING, "content": "<p></p>"}
        model = _stub_model(truth, {"jmespath": dict(_DEFAULT_JMESPATH)})
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            with self.assertRaises(UnlearnablePage) as caught:
                learn_mapping(model, _DOMAIN, _URL, posting, "detail")
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertEqual(str(caught.exception), _STEP5_MESSAGE)


class TestLearnDetailMappingBudget(unittest.TestCase):
    def test_d10_body_over_budget_raises_before_any_model_call(self):
        model = MagicMock()
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
            patch.dict(os.environ, {"EXTRACTION_NUM_CTX": "4100"}),
        ):
            with self.assertRaises(UnlearnablePage):
                learn_mapping(model, _DOMAIN, _URL, _POSTING, "detail")
            self.assertEqual(list(Path(tmp).iterdir()), [])
        model.generate_mapping_expected.assert_not_called()


class TestLearnDetailMappingCodeReply(unittest.TestCase):
    def test_d11_orchestrator_overrides_domains_and_type(self):
        truth = {
            "title": "Engineer",
            "company_name": "Acme",
            "description_source": {"field": "content", "html_escaped": True},
        }
        jmespath_reply = {
            "jmespath": dict(_DEFAULT_JMESPATH),
            "domains": ["evil.example"],
            "type": "index",
        }
        _, _, _, _, _, mapping_doc = _learn(truth, jmespath_reply=jmespath_reply)
        self.assertEqual(mapping_doc["domains"], [_DOMAIN])
        self.assertEqual(mapping_doc["type"], "detail")


class TestLearnDetailMappingArtifactSet(unittest.TestCase):
    """Grades the artifact set: a green expected.json paired with a mapping that
    reads the wrong field must still fail the generated suite."""

    _TRUTH = {
        "title": "Engineer",
        "company_name": "Acme",
        "description_source": {"field": "content", "html_escaped": True},
    }

    def _generated_suite_result(self, jmespath_block: dict) -> unittest.TestResult:
        model = _stub_model(self._TRUTH, {"jmespath": jmespath_block})
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("llm.adapter_files._ADAPTERS_DIR", Path(tmp)),
        ):
            names, _ = learn_mapping(model, _DOMAIN, _URL, _POSTING, "detail")
            test_path = Path(tmp) / f"{names.basename}_test.py"
            module_name = f"generated_{names.basename}_test"
            spec = importlib.util.spec_from_file_location(module_name, test_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
                test_class = getattr(module, names.test_class)
                suite = unittest.TestLoader().loadTestsFromTestCase(test_class)
                result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
            finally:
                del sys.modules[module_name]
        return result

    def test_d12_passes_for_a_correct_mapping(self):
        result = self._generated_suite_result(
            {
                "title": "title",
                "company_name": "company_name",
                "description": "markdown(unescape(content))",
            }
        )
        self.assertTrue(result.wasSuccessful())

    def test_d12_fails_when_unescape_is_dropped(self):
        result = self._generated_suite_result(
            {
                "title": "title",
                "company_name": "company_name",
                "description": "markdown(content)",
            }
        )
        self.assertFalse(result.wasSuccessful())


if __name__ == "__main__":
    unittest.main()
