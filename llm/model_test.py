import unittest
from unittest.mock import MagicMock, patch

from llm.model import LLMModel


class TestLLMModel(unittest.TestCase):
    @patch("llm.model.OllamaLLM")
    def test_generate_adapter(self, mock_ollama):
        mock_llm_instance = MagicMock()
        mock_llm_instance.invoke.return_value = "def extract(): pass"
        mock_ollama.return_value = mock_llm_instance

        model = LLMModel()
        result = model.generate_adapter(
            domain="example.com",
            raw_html="<html><body>Job</body></html>",
            base_adapter_code="class BaseAdapter:",
        )

        self.assertEqual(result, "def extract(): pass")
        mock_llm_instance.invoke.assert_called_once()

        prompt_arg = mock_llm_instance.invoke.call_args[0][0]
        self.assertIn("example.com", prompt_arg)
        self.assertIn("<html><body>Job</body></html>", prompt_arg)
        self.assertIn("class BaseAdapter:", prompt_arg)
