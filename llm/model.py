import logging
import os
from pathlib import Path
from string import Template

from langchain_ollama import OllamaLLM

logger = logging.getLogger(__name__)

# How much cleaned HTML to put in a prompt. The old 8k cap dropped everything on real
# pages: a listing's job links can start ~70k chars in — so the model saw only the
# header/nav. Keep within the model's context window (see OLLAMA_NUM_CTX).
_HTML_CHAR_BUDGET = int(os.getenv("LLM_HTML_CHARS", "120000"))

_PROMPT_DIR = Path(__file__).parent / "prompts"
_TEMPLATE_CACHE: dict[str, str] = {}


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
    "    description: str (as markdown), metadata: dict\n"
)

_ROLE = {
    "discovery": {
        "base_class": "DiscoveryAdapter",
        "requirements": (
            "Implement get_job_links(html, url) -> list[str] returning ONLY the URLs "
            "of individual job-detail postings, and get_next_page_links(html, url) -> "
            "list[str] returning ONLY pagination / next-page URLs. Both are absolute. "
            "Never put a pagination link in the job links, nor a job link in it."
        ),
        "schema": "",
        "test_contract": (
            "Your output is compared by **exact set** against a snapshot of this page: "
            "returning any extra item (e.g. a pagination link among the job links) or "
            "missing one **fails**. Be precise about which elements you select."
        ),
    },
    "extraction": {
        "base_class": "ExtractionAdapter",
        "requirements": (
            "Implement extract(html, url) -> dict matching the Silver schema below. "
            "For description, find the single element holding the posting body, remove "
            "any child nodes that are not part of it (apply widgets, share bars, "
            "related-jobs), and convert it with the shared helper — never hand-roll "
            "markdown: `from adapters.adapters._markdown import html_to_markdown`, "
            "then `description = html_to_markdown(node)`."
        ),
        "schema": _SILVER_SCHEMA,
        "test_contract": (
            "Your output dict is compared field-by-field against a snapshot of this "
            "page. title, company_name and description are required; title and "
            "company_name must match exactly; description must equal the markdown that "
            "html_to_markdown produces for the body you select, so use that helper and "
            "pick the right node; locations and categories are compared as sets; "
            "employment_type and metadata are optional. Extract what the page states — "
            "do not summarise or invent."
        ),
    },
}


# What the truth agent must enumerate per adapter type. Kept as a `$`-template (not
# str.format) because the output shapes contain literal JSON braces.
_EXPECTED = {
    "discovery": {
        "instructions": (
            "List every job-detail link and every next-page (pagination) link on this "
            "listing page."
        ),
        "output_shape": (
            '{"job_links": ["<absolute url>", ...], '
            '"next_page_links": ["<absolute url>", ...]}'
        ),
    },
    "extraction": {
        "instructions": (
            "Extract the job posting's fields into the Silver schema. Render "
            "description as markdown (headings with #, lists as - or 1., paragraphs "
            "preserved), with the top heading starting at level 1 (#)."
        ),
        "output_shape": (
            '{"title": "...", "company_name": "...", '
            '"employment_type": "... or null", "locations": ["..."], '
            '"categories": ["..."], "description": "...", "metadata": {}}'
        ),
    },
}


def build_expected_prompt(adapter_type: str, cleaned_html: str, url: str) -> str:
    """Render the truth-agent prompt asking for a grounded expected.json."""
    role = _EXPECTED[adapter_type]
    template = Template(_load_template("expected_agent.md"))
    return template.safe_substitute(
        adapter_type=adapter_type,
        role_instructions=role["instructions"],
        output_shape=role["output_shape"],
        url=url,
        cleaned_html=cleaned_html[:_HTML_CHAR_BUDGET],
    )


def build_code_prompt(
    adapter_type: str,
    cleaned_html: str,
    adapter_class: str,
    domains: list[str],
    base_code: str,
) -> str:
    """Render the code-agent prompt.

    The code agent never sees ``expected.json`` — only the base class and the HTML — so
    it must parse rather than hardcode.
    """
    role = _ROLE[adapter_type]
    return Template(_load_template("code_agent.md")).safe_substitute(
        adapter_type=adapter_type,
        adapter_class=adapter_class,
        base_class=role["base_class"],
        role_requirements=role["requirements"],
        silver_schema=role["schema"],
        test_contract=role["test_contract"],
        domains=list(domains),
        base_code=base_code,
        cleaned_html=cleaned_html[:_HTML_CHAR_BUDGET],
    )


class LLMModel:
    def __init__(
        self,
        model_name: str = "qwen3-coder:30b",
        base_url: str | None = None,
        num_ctx: int | None = None,
        temperature: float = 0.0,
        **kwargs,
    ):
        logger.info("Initializing Ollama with model: %s", model_name)
        if base_url is None:
            base_url = "http://localhost:11434"
        if num_ctx is None:
            # Ollama otherwise defaults to a ~2-4k token window that silently truncates
            # large pages regardless of the model's real capacity.
            num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "32768"))
        logger.info(
            "Connecting to Ollama at %s (num_ctx=%d, temperature=%s)",
            base_url,
            num_ctx,
            temperature,
        )
        self.llm = OllamaLLM(
            model=model_name,
            base_url=base_url,
            num_ctx=num_ctx,
            temperature=temperature,
            **kwargs,
        )

    def generate_response(self, prompt: str) -> str:
        return self.llm.invoke(prompt)

    def generate_expected(self, adapter_type: str, cleaned_html: str, url: str) -> str:
        """Generate the grounded snapshot (expected.json body) for a page."""
        return self.generate_response(
            build_expected_prompt(adapter_type, cleaned_html, url)
        )

    def generate_code(
        self,
        adapter_type: str,
        cleaned_html: str,
        adapter_class: str,
        domains: list[str],
        base_code: str,
    ) -> str:
        """Generate the adapter implementation for *adapter_class*."""
        return self.generate_response(
            build_code_prompt(
                adapter_type, cleaned_html, adapter_class, domains, base_code
            )
        )
