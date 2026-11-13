import json
import os
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from adapters.adapters._pay import PAY_PERIODS
from adapters.adapters.mapping import evaluate_expression
from llm.model import (
    _SILVER_FIELD_DEFINITIONS,
    LLMModel,
    build_code_prompt,
    build_expected_prompt,
    build_mapping_code_prompt,
    build_mapping_expected_prompt,
    index_num_ctx,
    parse_json_object,
)

# Never resolved: runfiles are per-file symlinks, so resolving would leave the runfiles
# tree for the source tree.
_FIXTURES = Path(__file__).parent.parent / "adapters" / "adapters" / "fixtures"


def _example_jmespath(prompt: str) -> dict[str, str]:
    """The ``jmespath`` block of the prompt's fenced JSON example."""
    match = re.search(r"```json\n(.*?)\n```", prompt, re.DOTALL)
    assert match is not None, "the prompt holds no fenced JSON example"
    return json.loads(match.group(1))["jmespath"]


def _object_nodes(node: object) -> list[dict]:
    """Every object in a parsed JSON tree, *node* itself included."""
    if isinstance(node, dict):
        found = [node]
        for value in node.values():
            found.extend(_object_nodes(value))
        return found
    if isinstance(node, list):
        return [found for item in node for found in _object_nodes(item)]
    return []


def _selects_nothing(value: object) -> bool:
    """Whether an expression's result carries no value from the document."""
    if value is None:
        return True
    if isinstance(value, dict):
        return all(_selects_nothing(item) for item in value.values())
    return False


class TestParseJsonObject(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(parse_json_object('{"a": 1}'), {"a": 1})

    def test_json_wrapped_in_fence_and_prose(self):
        raw = 'Here you go:\n```json\n{"a": 1}\n```'
        self.assertEqual(parse_json_object(raw), {"a": 1})

    def test_non_object_returns_empty(self):
        self.assertEqual(parse_json_object("not json at all"), {})
        self.assertEqual(parse_json_object("[1, 2]"), {})


class TestPromptBuilders(unittest.TestCase):
    def test_build_expected_prompt_discovery(self):
        prompt = build_expected_prompt(
            "discovery", "<html>JOBHTML</html>", "https://acme.com/jobs"
        )
        self.assertIn("JOBHTML", prompt)
        self.assertIn("https://acme.com/jobs", prompt)
        self.assertIn("job_links", prompt)
        self.assertIn("next_page_links", prompt)
        # $-placeholders must all be substituted.
        self.assertNotIn("$cleaned_html", prompt)

    def test_prompt_builders_substitute_the_body_verbatim(self):
        # Both builders substitute cleaned_html verbatim: sizing it is the caller's
        # job, so a low LLM_HTML_CHARS here must not truncate either rendered prompt.
        body = "A" * 490 + "TAIL"
        with patch.dict(os.environ, {"LLM_HTML_CHARS": "10"}):
            expected_prompt = build_expected_prompt(
                "discovery", body, "https://acme.com/jobs"
            )
            code_prompt = build_code_prompt(
                "discovery",
                body,
                "AcmeDiscoveryAdapter",
                ["acme.com"],
                "class BaseX: pass",
            )
        self.assertIn("TAIL", expected_prompt)
        self.assertIn("TAIL", code_prompt)

    def test_build_expected_prompt_extraction_shape(self):
        prompt = build_expected_prompt(
            "extraction", "<html></html>", "https://acme.com/job/1"
        )
        self.assertIn("company_name", prompt)
        self.assertIn("locations", prompt)
        self.assertIn("markdown", prompt)  # description is rendered as markdown

    def test_build_code_prompt_has_class_domains_and_html_but_not_answer(self):
        prompt = build_code_prompt(
            "discovery",
            "<html>MARKER_HTML</html>",
            "AcmeDiscoveryAdapter",
            ["acme.com", "www.acme.com"],
            "class BaseX: pass",
        )
        self.assertIn("AcmeDiscoveryAdapter", prompt)
        self.assertIn("acme.com", prompt)
        self.assertIn("DiscoveryAdapter", prompt)
        self.assertIn("MARKER_HTML", prompt)
        self.assertIn("exact set", prompt)  # discovery test contract substituted
        self.assertNotIn("$cleaned_html", prompt)  # all placeholders substituted

    def test_build_code_prompt_extraction_has_schema_and_contract(self):
        prompt = build_code_prompt(
            "extraction",
            "<html>MARKER_HTML</html>",
            "AcmeExtractionAdapter",
            ["acme.com"],
            "class BaseX: pass",
        )
        self.assertIn("ExtractionAdapter", prompt)
        self.assertIn("Silver schema", prompt)
        self.assertIn("company_name", prompt)
        self.assertIn("html_to_markdown", prompt)  # description uses the shared helper
        self.assertNotIn("$test_contract", prompt)  # extraction contract substituted

    def test_build_mapping_expected_prompt_carries_the_absolute_url_rule(self):
        prompt = build_mapping_expected_prompt(
            "index", '{"jobs": ["MARKER_BODY"]}', "https://boards.acme.com/api"
        )
        self.assertIn("MARKER_BODY", prompt)
        self.assertIn("https://boards.acme.com/api", prompt)
        self.assertIn("job_links", prompt)
        self.assertIn("absolute", prompt)
        self.assertNotIn("$body", prompt)

    def test_build_mapping_expected_prompt_never_reuses_the_html_template(self):
        # expected_agent.md ends under a "Cleaned page HTML" heading, which would
        # hand a JSON response to the agent under a heading calling it HTML.
        prompt = build_mapping_expected_prompt(
            "index", "{}", "https://boards.acme.com/api"
        )
        self.assertNotIn("Cleaned page HTML", prompt)

    def test_build_mapping_code_prompt_states_the_reply_shape(self):
        prompt = build_mapping_code_prompt(
            "index", '{"jobs": ["MARKER_BODY"]}', ["boards.acme.com"]
        )
        self.assertIn("MARKER_BODY", prompt)
        self.assertIn("boards.acme.com", prompt)
        self.assertIn("postings", prompt)
        self.assertIn("posting_url", prompt)
        self.assertIn("jmespath", prompt)
        self.assertNotIn("$body", prompt)

    def test_build_mapping_expected_prompt_detail_shape(self):
        prompt = build_mapping_expected_prompt(
            "detail", '{"title": "MARKER"}', "https://boards.acme.com/api/jobs/1"
        )
        self.assertIn("description_source", prompt)
        self.assertIn("html_escaped", prompt)
        self.assertNotIn("job_links", prompt)

    def test_build_mapping_code_prompt_detail_shape(self):
        prompt = build_mapping_code_prompt(
            "detail", '{"title": "MARKER"}', ["boards.acme.com"]
        )
        self.assertIn("markdown(", prompt)
        self.assertIn("unescape(", prompt)
        self.assertIn("never a string literal", prompt)
        self.assertNotIn("posting_url", prompt)

    def test_mapping_prompt_builders_raise_for_an_unknown_type(self):
        with self.assertRaises(ValueError):
            build_mapping_expected_prompt("listing", "{}", "https://acme.com")
        with self.assertRaises(ValueError):
            build_mapping_code_prompt("listing", "{}", ["acme.com"])

    @patch("llm.model.OllamaLLM")
    def test_generate_mapping_expected_invokes_llm_once(self, mock_ollama):
        instance = MagicMock()
        instance.invoke.return_value = '{"job_links": []}'
        mock_ollama.return_value = instance

        model = LLMModel()
        out = model.generate_mapping_expected(
            "index", '{"jobs": []}', "https://boards.acme.com/api"
        )
        self.assertEqual(out, '{"job_links": []}')
        instance.invoke.assert_called_once()
        self.assertIn("boards.acme.com", instance.invoke.call_args[0][0])

    @patch("llm.model.OllamaLLM")
    def test_generate_mapping_invokes_llm_once(self, mock_ollama):
        instance = MagicMock()
        instance.invoke.return_value = '{"jmespath": {"postings": "jobs[]"}}'
        mock_ollama.return_value = instance

        model = LLMModel()
        out = model.generate_mapping("index", '{"jobs": []}', ["boards.acme.com"])
        self.assertEqual(out, '{"jmespath": {"postings": "jobs[]"}}')
        instance.invoke.assert_called_once()
        self.assertIn("boards.acme.com", instance.invoke.call_args[0][0])

    def test_index_num_ctx_reads_env_per_call(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INDEX_NUM_CTX", None)
            self.assertEqual(index_num_ctx(), 65536)
            with patch.dict(os.environ, {"INDEX_NUM_CTX": "8192"}):
                self.assertEqual(index_num_ctx(), 8192)

    @patch("llm.model.OllamaLLM")
    def test_generate_code_invokes_llm_once(self, mock_ollama):
        instance = MagicMock()
        instance.invoke.return_value = "class A(DiscoveryAdapter): pass"
        mock_ollama.return_value = instance

        model = LLMModel()
        out = model.generate_code(
            "discovery",
            "<html>MARKER_HTML</html>",
            "AcmeDiscoveryAdapter",
            ["acme.com"],
            "base",
        )
        self.assertEqual(out, "class A(DiscoveryAdapter): pass")
        instance.invoke.assert_called_once()
        self.assertIn("MARKER_HTML", instance.invoke.call_args[0][0])

    @patch("llm.model.OllamaLLM")
    def test_generate_expected_invokes_llm_once(self, mock_ollama):
        instance = MagicMock()
        instance.invoke.return_value = '{"job_links": [], "next_page_links": []}'
        mock_ollama.return_value = instance

        model = LLMModel()
        out = model.generate_expected(
            "discovery", "<html></html>", "https://acme.com/jobs"
        )
        self.assertEqual(out, '{"job_links": [], "next_page_links": []}')
        instance.invoke.assert_called_once()
        self.assertIn("https://acme.com/jobs", instance.invoke.call_args[0][0])

    @patch("llm.model.OllamaLLM")
    def test_model_name_defaults_when_env_unset(self, mock_ollama):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OLLAMA_MODEL", None)
            model = LLMModel()
        self.assertEqual(model.model_name, "qwen3-coder:30b")
        self.assertEqual(mock_ollama.call_args.kwargs["model"], "qwen3-coder:30b")

    @patch("llm.model.OllamaLLM")
    def test_model_name_reads_env_var(self, mock_ollama):
        with patch.dict(os.environ, {"OLLAMA_MODEL": "qwen3.8:27b-mlx"}):
            model = LLMModel()
        self.assertEqual(model.model_name, "qwen3.8:27b-mlx")
        self.assertEqual(mock_ollama.call_args.kwargs["model"], "qwen3.8:27b-mlx")

    @patch("llm.model.OllamaLLM")
    def test_explicit_model_name_beats_env_var(self, mock_ollama):
        with patch.dict(os.environ, {"OLLAMA_MODEL": "qwen3.8:27b-mlx"}):
            model = LLMModel(model_name="explicit-model")
        self.assertEqual(model.model_name, "explicit-model")
        self.assertEqual(mock_ollama.call_args.kwargs["model"], "explicit-model")


_RULE = "Omit a metadata key whose value"
_URL = "https://acme.example/x"
_DOMAINS = ["acme.example"]


class TestSilverFieldPrompts(unittest.TestCase):
    def test_extraction_prompts_carry_the_field_definitions(self):
        expected = build_expected_prompt("extraction", "MARKER", _URL)
        code = build_code_prompt(
            "extraction", "MARKER", "AcmeExtractionAdapter", _DOMAINS, "base"
        )
        self.assertIn(_SILVER_FIELD_DEFINITIONS, expected)
        self.assertIn(_SILVER_FIELD_DEFINITIONS, code)
        self.assertIn(_RULE, expected)
        self.assertNotIn(_RULE, code)

    def test_discovery_prompts_carry_no_field_definitions(self):
        expected = build_expected_prompt("discovery", "MARKER", _URL)
        code = build_code_prompt(
            "discovery", "MARKER", "AcmeDiscoveryAdapter", _DOMAINS, "base"
        )
        for prompt in (expected, code):
            self.assertNotIn(_SILVER_FIELD_DEFINITIONS, prompt)
            self.assertNotIn(_RULE, prompt)

    def test_detail_mapping_prompts_carry_the_field_definitions(self):
        expected = build_mapping_expected_prompt("detail", "MARKER", _URL)
        code = build_mapping_code_prompt("detail", "MARKER", _DOMAINS)
        for prompt in (expected, code):
            self.assertIn(_SILVER_FIELD_DEFINITIONS, prompt)
            self.assertNotIn("$silver_field_definitions", prompt)
        self.assertIn(_RULE, expected)
        self.assertNotIn("any other metadata", expected)
        self.assertNotIn(_RULE, code)

    def test_index_mapping_prompts_carry_no_field_definitions(self):
        expected = build_mapping_expected_prompt("index", "MARKER", _URL)
        code = build_mapping_code_prompt("index", "MARKER", _DOMAINS)
        for prompt in (expected, code):
            self.assertNotIn(_SILVER_FIELD_DEFINITIONS, prompt)
            self.assertNotIn("$silver_field_definitions", prompt)

    def test_mapping_code_examples_select_nothing_from_a_committed_payload(self):
        index_docs = sorted(_FIXTURES.glob("*/index.json"))
        detail_docs = sorted(_FIXTURES.glob("*/detail.json"))
        self.assertTrue(index_docs, "no index.json fixture, so this proves nothing")
        self.assertTrue(detail_docs, "no detail.json fixture, so this proves nothing")

        detail_example = _example_jmespath(
            build_mapping_code_prompt("detail", "MARKER", _DOMAINS)
        )
        index_example = _example_jmespath(
            build_mapping_code_prompt("index", "MARKER", _DOMAINS)
        )
        checks: list[tuple[str, str, Path, object]] = []
        for path in detail_docs:
            doc = json.loads(path.read_text())
            for expr in detail_example.values():
                checks.append(("mapping_detail_code_agent.md", expr, path, doc))
        for path in index_docs:
            doc = json.loads(path.read_text())
            checks.append(
                ("mapping_code_agent.md", index_example["postings"], path, doc)
            )
            for node in _object_nodes(doc):
                checks.append(
                    ("mapping_code_agent.md", index_example["posting_url"], path, node)
                )
        for template, expr, path, doc in checks:
            with self.subTest(expr=expr, path=str(path)):
                value = evaluate_expression(expr, doc)  # type: ignore[arg-type]
                self.assertTrue(
                    _selects_nothing(value),
                    f"{expr!r} selects {value!r} from {path}: change the example in "
                    f"llm/prompts/{template}, never the fixture",
                )


class TestPayPrompts(unittest.TestCase):
    def setUp(self) -> None:
        self.html_truth = build_expected_prompt("extraction", "MARKER", _URL)
        self.html_code = build_code_prompt(
            "extraction", "MARKER", "AcmeExtractionAdapter", _DOMAINS, "base"
        )
        self.detail_truth = build_mapping_expected_prompt("detail", "MARKER", _URL)
        self.detail_code = build_mapping_code_prompt("detail", "MARKER", _DOMAINS)

    def test_definition_names_every_period(self):
        phrase = "period is one of " + ", ".join(PAY_PERIODS[:-1]) + " or "
        self.assertIn(phrase + PAY_PERIODS[-1] + ".", _SILVER_FIELD_DEFINITIONS)

    def test_extraction_kind_prompts_define_pay(self):
        for prompt in (
            self.html_truth,
            self.html_code,
            self.detail_truth,
            self.detail_code,
        ):
            self.assertIn("- pay: ", prompt)
        others = (
            build_expected_prompt("discovery", "MARKER", _URL),
            build_code_prompt(
                "discovery", "MARKER", "AcmeDiscoveryAdapter", _DOMAINS, "base"
            ),
            build_mapping_expected_prompt("index", "MARKER", _URL),
            build_mapping_code_prompt("index", "MARKER", _DOMAINS),
        )
        for prompt in others:
            self.assertNotIn("- pay: ", prompt)

    def test_extraction_code_prompt_lists_pay_in_the_schema(self):
        self.assertIn("pay: dict | None", self.html_code)

    def test_truth_prompts_ask_for_pay(self):
        shape = '"pay": {"min": <number or null>, "max": <number or null>'
        self.assertIn(shape, self.html_truth)
        self.assertIn(shape, self.detail_truth)

    def test_detail_code_prompt_documents_the_pay_functions(self):
        self.assertIn("hundredths(n)", self.detail_code)
        self.assertIn("pay_period(s)", self.detail_code)
        self.assertIn("pay", _example_jmespath(self.detail_code))

    def test_prompts_say_how_one_number_is_stored(self):
        for text in (
            "A single stated amount goes in both min and max.",
            "A bound is null only when the posting states just one end",
            "Never invent a bound.",
        ):
            self.assertIn(text, _SILVER_FIELD_DEFINITIONS)
        self.assertIn("maps that field into both", self.detail_code)
        self.assertIn("never to a copy", self.detail_code)


if __name__ == "__main__":
    unittest.main()
