import logging

from langchain_ollama import OllamaLLM

logger = logging.getLogger(__name__)


class LLMModel:
    def __init__(self, model_name: str = "qwen3:4b", base_url: str = None, **kwargs):
        """Initialize with Ollama."""
        logger.info(f"Initializing Ollama with model: {model_name}")
        if base_url is None:
            base_url = "http://localhost:11434"
        logger.info(f"Connecting to Ollama at: {base_url}")
        self.llm = OllamaLLM(model=model_name, base_url=base_url, **kwargs)

    def generate_response(self, prompt: str) -> str:
        """Generate a response from the LLM."""
        return self.llm.invoke(prompt)
