import unittest
from unittest.mock import MagicMock, patch

from llm.model import LLMModel, build_code_prompt, build_test_prompt


class TestLLMModel(unittest.TestCase):
    @patch("llm.model.OllamaLLM")
    def test_generate_adapter_discovery(self, mock_ollama):
        mock_llm_instance = MagicMock()
        mock_llm_instance.invoke.return_value = (
            "class GoogleDiscoveryAdapter(DiscoveryAdapter): pass"
        )
        mock_ollama.return_value = mock_llm_instance

        model = LLMModel()
        result = model.generate_adapter(
            domain="example.com",
            raw_html="<html><body>Job</body></html>",
            adapter_type="discovery",
            base_code="class DiscoveryAdapter:",
            test_base_code="class BaseDiscoveryAdapterTest:",
        )

        self.assertEqual(result, "class GoogleDiscoveryAdapter(DiscoveryAdapter): pass")
        mock_llm_instance.invoke.assert_called_once()

        prompt_arg = mock_llm_instance.invoke.call_args[0][0]
        self.assertIn("example.com", prompt_arg)
        self.assertIn("<html><body>Job</body></html>", prompt_arg)
        self.assertIn("class DiscoveryAdapter:", prompt_arg)
        self.assertIn("class BaseDiscoveryAdapterTest:", prompt_arg)
        self.assertIn("DiscoveryAdapter", prompt_arg)
        self.assertIn("BaseDiscoveryAdapterTest", prompt_arg)

    @patch("llm.model.OllamaLLM")
    def test_generate_adapter_extraction(self, mock_ollama):
        mock_llm_instance = MagicMock()
        mock_llm_instance.invoke.return_value = (
            "class GoogleExtractionAdapter(ExtractionAdapter): pass"
        )
        mock_ollama.return_value = mock_llm_instance

        model = LLMModel()
        result = model.generate_adapter(
            domain="example.com",
            raw_html="<html><body>Job</body></html>",
            adapter_type="extraction",
            base_code="class ExtractionAdapter:",
            test_base_code="class BaseExtractionAdapterTest:",
        )

        self.assertEqual(
            result, "class GoogleExtractionAdapter(ExtractionAdapter): pass"
        )
        mock_llm_instance.invoke.assert_called_once()

        prompt_arg = mock_llm_instance.invoke.call_args[0][0]
        self.assertIn("example.com", prompt_arg)
        self.assertIn("class ExtractionAdapter:", prompt_arg)
        self.assertIn("class BaseExtractionAdapterTest:", prompt_arg)
        self.assertIn("ExtractionAdapter", prompt_arg)
        self.assertIn("BaseExtractionAdapterTest", prompt_arg)


class TestPromptBuilders(unittest.TestCase):
    def test_build_test_prompt_discovery(self):
        prompt = build_test_prompt(
            "discovery",
            "<html>JOBHTML</html>",
            "adapters.adapters.acme_discovery_v1",
            "AcmeDiscoveryAdapter",
            "class BaseDiscoveryAdapterTest: pass",
        )
        import_line = (
            "from adapters.adapters.acme_discovery_v1 import AcmeDiscoveryAdapter"
        )
        self.assertIn(import_line, prompt)
        self.assertIn("BaseDiscoveryAdapterTest", prompt)
        self.assertIn("JOBHTML", prompt)
        self.assertIn("get_job_links", prompt)

    def test_build_test_prompt_extraction_includes_schema(self):
        prompt = build_test_prompt(
            "extraction",
            "<html></html>",
            "adapters.adapters.acme_extraction_v1",
            "AcmeExtractionAdapter",
            "class BaseExtractionAdapterTest: pass",
        )
        self.assertIn("Silver schema", prompt)
        self.assertIn("company_name", prompt)

    def test_build_code_prompt_includes_test_source_and_domains(self):
        prompt = build_code_prompt(
            "discovery",
            "<html>H</html>",
            "AcmeDiscoveryAdapter",
            ["acme.com", "www.acme.com"],
            "class BaseX: pass",
            "def test_x(): assert True",
        )
        self.assertIn("def test_x(): assert True", prompt)
        self.assertIn("AcmeDiscoveryAdapter", prompt)
        self.assertIn("acme.com", prompt)
        self.assertIn("DiscoveryAdapter", prompt)

    @patch("llm.model.OllamaLLM")
    def test_generate_code_invokes_llm_once_with_test(self, mock_ollama):
        instance = MagicMock()
        instance.invoke.return_value = "class A(DiscoveryAdapter): pass"
        mock_ollama.return_value = instance

        model = LLMModel()
        out = model.generate_code(
            "discovery",
            "<html></html>",
            "AcmeDiscoveryAdapter",
            ["acme.com"],
            "base",
            "def test(): pass",
        )
        self.assertEqual(out, "class A(DiscoveryAdapter): pass")
        instance.invoke.assert_called_once()
        self.assertIn("def test(): pass", instance.invoke.call_args[0][0])
