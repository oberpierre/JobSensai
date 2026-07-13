import logging
from pathlib import Path

from langchain_ollama import OllamaLLM

logger = logging.getLogger(__name__)

_PROMPT_FILE = Path(__file__).parent / "prompts" / "runtime_agent.txt"
_PROMPT_TEMPLATE: str | None = None


def _load_prompt_template() -> str:
    global _PROMPT_TEMPLATE
    if _PROMPT_TEMPLATE is None:
        _PROMPT_TEMPLATE = _PROMPT_FILE.read_text()
    return _PROMPT_TEMPLATE


class LLMModel:
    def __init__(
        self, model_name: str = "qwen3-coder:30b", base_url: str | None = None, **kwargs
    ):
        logger.info("Initializing Ollama with model: %s", model_name)
        if base_url is None:
            base_url = "http://localhost:11434"
        logger.info("Connecting to Ollama at: %s", base_url)
        self.llm = OllamaLLM(model=model_name, base_url=base_url, **kwargs)

    def generate_response(self, prompt: str) -> str:
        return self.llm.invoke(prompt)

    def generate_adapter(
        self,
        domain: str,
        raw_html: str,
        adapter_type: str,
        base_code: str,
        test_base_code: str,
        previous_code: str | None = None,
        error_message: str | None = None,
    ) -> str:
        """Generate (or fix) an adapter for *domain* using the runtime_agent prompt."""
        if adapter_type == "discovery":
            test_base_class = "BaseDiscoveryAdapterTest"
            base_class_section = (
                "Generate a DiscoveryAdapter that:\n"
                "  • implements get_job_links(html, url) -> list[str]\n"
                "  • implements get_next_page_links(html, url) -> list[str]\n"
                "Both methods must return absolute URLs only."
            )
        else:
            test_base_class = "BaseExtractionAdapterTest"
            base_class_section = (
                "Generate an ExtractionAdapter that:\n"
                "  • implements extract(html, url) -> dict\n"
                "The dict must conform to the Silver Schema defined below."
            )

        if previous_code and error_message:
            refinement_section = (
                "PREVIOUS ATTEMPT — FIX THE FOLLOWING ERROR\n"
                "==========================================\n\n"
                f"Error:\n{error_message}\n\n"
                f"Previous code:\n{previous_code}"
            )
        else:
            refinement_section = ""

        template = _load_prompt_template()
        prompt = template.format(
            domain=domain,
            adapter_type=adapter_type.upper(),
            base_class_section=base_class_section,
            html_snippet=raw_html[:8000],
            base_code=base_code,
            test_base_code=test_base_code,
            test_base_class=test_base_class,
            refinement_section=refinement_section,
        )
        return self.generate_response(prompt)
