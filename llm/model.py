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
        self,
        domain: str,
        raw_html: str,
        adapter_type: str,
        base_code: str,
        test_base_code: str,
    ) -> str:
        """Generate an adapter implementation for the given domain and HTML."""

        if adapter_type == "discovery":
            base_class = "DiscoveryAdapter"
            test_base_class = "BaseDiscoveryAdapterTest"
            methods_to_implement = "`get_job_links` and `get_next_page_links`"
            test_desc = (
                f"test the extraction methods based on the `{test_base_class}` contract"
            )
        else:
            base_class = "ExtractionAdapter"
            test_base_class = "BaseExtractionAdapterTest"
            methods_to_implement = "`extract`"
            test_desc = (
                f"test the `extract` method based on the `{test_base_class}` contract"
            )

        prompt = f"""
You are an expert Python web scraping engineer.
Your task is to create a Python web scraper adapter for the domain: {domain}

Here is the {base_class} class you MUST inherit from and fully implement:
```python
{base_code}
```

Here is the {test_base_class} class your test MUST inherit from:
```python
{test_base_code}
```

Here is a sample of the raw HTML from the website:
```html
{raw_html[:10000]}
```

Requirements:
1. Inherit from `{base_class}`.
2. Implement ALL abstract methods: {methods_to_implement}.
3. Use BeautifulSoup (bs4) for parsing if needed.
4. ONLY return valid Python code. Do NOT enclose it in markdown blocks.
5. Provide a valid unittest file using the `unittest` library that inherits from `{test_base_class}`.
   You must implement all abstract methods of `{test_base_class}` to {test_desc}.
   You must import {test_base_class} like `from adapaters.adapters.base_test import {test_base_class}`.
6. Separate the adapter class and the test code with a comment `# --- TEST CODE ---`.
"""  # noqa: E501
        return self.generate_response(prompt)
