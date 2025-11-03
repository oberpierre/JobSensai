import logging

from langchain_ollama import OllamaLLM

logger = logging.getLogger(__name__)


class LLMModel:
    def __init__(self, model_name: str = "qwen3:4b", **kwargs):
        """Initialize with Ollama."""
        logger.info(f"Initializing Ollama with model: {model_name}")
        self.llm = OllamaLLM(model=model_name, **kwargs)

    def generate_response(self, prompt: str) -> str:
        """Generate a response from the LLM."""
        return self.llm.invoke(prompt)
