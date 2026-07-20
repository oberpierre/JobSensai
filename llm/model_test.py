import unittest
from unittest.mock import MagicMock, patch

from llm.model import LLMModel, build_code_prompt, build_expected_prompt


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

    def test_build_expected_prompt_extraction_shape(self):
        prompt = build_expected_prompt(
            "extraction", "<html></html>", "https://acme.com/job/1"
        )
        self.assertIn("company_name", prompt)
        self.assertIn("locations", prompt)

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
        self.assertNotIn("$cleaned_html", prompt)  # all placeholders substituted

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
