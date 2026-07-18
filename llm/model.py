import logging
from pathlib import Path

from langchain_ollama import OllamaLLM

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).parent / "prompts"
_PROMPT_FILE = _PROMPT_DIR / "runtime_agent.txt"
_PROMPT_TEMPLATE: str | None = None
_TEMPLATE_CACHE: dict[str, str] = {}


def _load_prompt_template() -> str:
    global _PROMPT_TEMPLATE
    if _PROMPT_TEMPLATE is None:
        _PROMPT_TEMPLATE = _PROMPT_FILE.read_text()
    return _PROMPT_TEMPLATE


def _load_template(name: str) -> str:
    if name not in _TEMPLATE_CACHE:
        _TEMPLATE_CACHE[name] = (_PROMPT_DIR / name).read_text()
    return _TEMPLATE_CACHE[name]


# Injected verbatim into the extraction prompts (kept brace-free so str.format leaves it
# untouched). Discovery adapters get an empty schema section.
_SILVER_SCHEMA = (
    "\nThe extract() dict must match this Silver schema (all keys required):\n"
    "    title: str, company_name: str, employment_type: str | None,\n"
    "    locations: list[str], categories: list[str],\n"
    "    description: str, metadata: dict\n"
)

_ROLE = {
    "discovery": {
        "base_class": "DiscoveryAdapter",
        "test_base_class": "BaseDiscoveryAdapterTest",
        "requirements": (
            "Implement get_job_links(html, url) -> list[str] and "
            "get_next_page_links(html, url) -> list[str]; "
            "both return absolute URLs only."
        ),
        "schema": "",
    },
    "extraction": {
        "base_class": "ExtractionAdapter",
        "test_base_class": "BaseExtractionAdapterTest",
        "requirements": (
            "Implement extract(html, url) -> dict matching the Silver schema below."
        ),
        "schema": _SILVER_SCHEMA,
    },
}


def build_test_prompt(
    adapter_type: str,
    cleaned_html: str,
    adapter_module: str,
    adapter_class: str,
    test_base_code: str,
) -> str:
    """Render the test-agent prompt."""
    role = _ROLE[adapter_type]
    return _load_template("test_agent.txt").format(
        adapter_type=adapter_type,
        adapter_module=adapter_module,
        adapter_class=adapter_class,
        test_base_class=role["test_base_class"],
        role_requirements=role["requirements"],
        silver_schema=role["schema"],
        test_base_code=test_base_code,
        cleaned_html=cleaned_html[:8000],
    )


def build_code_prompt(
    adapter_type: str,
    cleaned_html: str,
    adapter_class: str,
    domains: list[str],
    base_code: str,
    test_source: str,
) -> str:
    """Render the code-agent prompt."""
    role = _ROLE[adapter_type]
    return _load_template("code_agent.txt").format(
        adapter_type=adapter_type,
        adapter_class=adapter_class,
        base_class=role["base_class"],
        role_requirements=role["requirements"],
        silver_schema=role["schema"],
        domains=list(domains),
        base_code=base_code,
        test_source=test_source,
        cleaned_html=cleaned_html[:8000],
    )


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

    def generate_test(
        self,
        adapter_type: str,
        cleaned_html: str,
        adapter_module: str,
        adapter_class: str,
        test_base_code: str,
    ) -> str:
        """Generate the unittest test for an adapter (test-first)."""
        return self.generate_response(
            build_test_prompt(
                adapter_type,
                cleaned_html,
                adapter_module,
                adapter_class,
                test_base_code,
            )
        )

    def generate_code(
        self,
        adapter_type: str,
        cleaned_html: str,
        adapter_class: str,
        domains: list[str],
        base_code: str,
        test_source: str,
    ) -> str:
        """Generate the adapter implementation that must satisfy *test_source*."""
        return self.generate_response(
            build_code_prompt(
                adapter_type,
                cleaned_html,
                adapter_class,
                domains,
                base_code,
                test_source,
            )
        )

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
