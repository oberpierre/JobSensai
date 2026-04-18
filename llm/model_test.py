import unittest
from unittest.mock import MagicMock, patch

from llm.model import LLMModel


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
