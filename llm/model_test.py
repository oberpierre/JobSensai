import os
import unittest
from unittest.mock import MagicMock, patch

from llm.model import (
    LLMModel,
    build_code_prompt,
    build_expected_prompt,
    build_mapping_code_prompt,
    build_mapping_expected_prompt,
    index_num_ctx,
    parse_json_object,
)


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


if __name__ == "__main__":
    unittest.main()
