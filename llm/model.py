import logging

from langchain_ollama import OllamaLLM

logger = logging.getLogger(__name__)


class LLMModel:
    def __init__(
        self, model_name: str = "qwen3:4b", base_url: str | None = None, **kwargs
    ):
        """Initialize with Ollama."""
        logger.info(f"Initializing Ollama with model: {model_name}")
        if base_url is None:
            base_url = "http://localhost:11434"
        logger.info(f"Connecting to Ollama at: {base_url}")
        self.llm = OllamaLLM(model=model_name, base_url=base_url, **kwargs)

    def generate_response(self, prompt: str) -> str:
        """Generate a response from the LLM."""
        return self.llm.invoke(prompt)

    def generate_adapter(
        self, domain: str, raw_html: str, base_adapter_code: str
    ) -> str:
        """Generate a BaseAdapter implementation for the given domain and HTML."""
        prompt = f"""
You are an expert Python web scraping engineer.
Your task is to create a Python web scraper adapter for the domain: {domain}

Here is the BaseAdapter class you MUST inherit from and fully implement:
```python
{base_adapter_code}
```

Here is a sample of the raw HTML from the website:
```html
{raw_html[:3000]} # Truncating to avoid passing massive HTML, but enough for structure
```

Requirements:
1. Inherit from `BaseAdapter`.
2. Implement ALL abstract methods, including `get_job_links` and `extract`.
3. The `extract` method MUST return a Pydantic `JobPosting` object.
4. ONLY return valid Python code. Do NOT enclose it in markdown blocks.
5. Provide a valid test case testing the `extract()` method.
"""
        return self.generate_response(prompt)
