"""Learn an index or detail mapping from an API response, test-first, like an adapter.

The document is data rather than code, so the two agents here write a JMESPath
`jmespath` block instead of Python: a truth agent grounds what the response or
posting states, then a code agent writes the expression that finds it.
"""

import copy
import html
import json

import jmespath

from adapters.adapters._markdown import html_to_markdown
from adapters.adapters.mapping import MappingError, evaluate_expression
from llm.adapter_files import (
    _SILVER_FIELDS,
    MappingNames,
    _is_grounded_text,
    _mapping_names,
    _write_mapping,
    _write_mapping_snapshot,
)
from llm.learning_errors import TruthAgentUnreadable, UnlearnablePage
from llm.model import (
    LLMModel,
    extraction_num_ctx,
    index_num_ctx,
    parse_json_object,
    strip_code_fences,
)

# Tokens reserved for the prompt scaffold around the body and the model's reply,
# subtracted from the context window before sizing the body to it.
_PROMPT_RESERVE_TOKENS = 4096

# JSON is denser per token than prose, so this deliberately underestimates rather
# than risk cutting a prompt mid-token.
_JSON_CHARS_PER_TOKEN = 2


def budget_chars(mapping_type: str) -> int:
    """The character budget a mapping body must fit, sized to its stage's window.

    The only place this arithmetic is written: `process_task` checks it is
    positive before taking a lease, and `learn_mapping` sizes or trims to it. Two
    copies would let the check guard a budget nothing reads.
    """
    if mapping_type == "index":
        window = index_num_ctx()
    elif mapping_type == "detail":
        window = extraction_num_ctx()
    else:
        raise ValueError(
            f"budget_chars supports mapping_type 'index' or 'detail', got "
            f"{mapping_type!r}"
        )
    window -= _PROMPT_RESERVE_TOKENS
    return window * _JSON_CHARS_PER_TOKEN


def _find_largest_array(node: object) -> list | None:
    """Return the array with the most elements anywhere in *node*, by reference.

    A reference into the (already copied) document, not a copy of it, so the
    caller's `.pop()` mutates the tree it walked rather than a throwaway.
    """
    best = node if isinstance(node, list) else None
    if isinstance(node, dict):
        children = node.values()
    elif isinstance(node, list):
        children = node
    else:
        children = ()
    for child in children:
        candidate = _find_largest_array(child)
        if candidate is not None and (best is None or len(candidate) > len(best)):
            best = candidate
    return best


def _trim_to_budget(document: dict | list, budget: int) -> tuple[dict | list, str]:
    """Drop array elements until the serialisation fits *budget*.

    Repeatedly drops the last element of the array with the most elements,
    wherever it sits, with no eligibility rule and no floor: on any real feed the
    postings array is the longest by a wide margin. The refusal is evaluated
    before each drop, which is what stops an all-singleton document from
    emptying its arrays and then indexing an empty list.
    """
    trimmed = copy.deepcopy(document)
    text = json.dumps(trimmed, indent=2)
    while len(text) > budget:
        array = _find_largest_array(trimmed)
        if array is None or len(array) <= 1:
            raise UnlearnablePage(
                f"response is {len(text)} chars, over the {budget}-char budget, and "
                "no array in it has more than one element left to drop"
            )
        array.pop()
        text = json.dumps(trimmed, indent=2)
    return trimmed, text


def _write_generated_mapping_document(
    names: MappingNames, model: LLMModel, mapping_type: str, domain: str, text: str
) -> None:
    """Ask the code agent for the `jmespath` block and write the finished document.

    Shared by the index and detail flows: both let the orchestrator overwrite
    version/type/domains rather than trust what the model returned for them, since
    an invented hostname would otherwise produce a document that routes nothing.
    """
    code_reply = model.generate_mapping(mapping_type, text, [domain])
    parsed_code = parse_json_object(strip_code_fences(code_reply))
    if parsed_code == {}:
        # A reviewer's question is what the model produced, not what could be
        # salvaged from it, so the unreadable reply is written verbatim.
        _write_mapping(names, code_reply)
        return
    document_out = {
        **parsed_code,
        "version": 1,
        "type": mapping_type,
        "domains": [domain],
    }
    _write_mapping(names, json.dumps(document_out, indent=2))


def _learn_index_mapping(
    model: LLMModel, domain: str, url: str, document: dict | list
) -> tuple[MappingNames, str]:
    names = _mapping_names(domain, "index")
    _trimmed, trimmed_text = _trim_to_budget(document, budget_chars("index"))

    truth = parse_json_object(
        model.generate_mapping_expected("index", trimmed_text, url)
    )
    if truth == {}:
        raise TruthAgentUnreadable("truth agent reply could not be parsed")
    job_links = truth.get("job_links", [])
    if not job_links:
        raise UnlearnablePage("truth agent grounded no job links")
    # Required by IndexMappingSnapshotTest as the urljoin base a relative
    # posting address resolves against.
    expected = {"url": url, "job_links": job_links}
    _write_mapping_snapshot(
        names, "index.json", trimmed_text, expected, "IndexMappingSnapshotTest"
    )
    _write_generated_mapping_document(names, model, "index", domain, trimmed_text)
    return names, model.model_name


def _calls_markdown_or_unescape(node: object) -> bool:
    """Walk a compiled expression's parsed tree for a `markdown` or `unescape` call.

    Such a source already converts, so the orchestrator rendering it again would
    convert the result a second time.
    """
    if not isinstance(node, dict):
        return False
    if node.get("type") == "function_expression" and node.get("value") in (
        "markdown",
        "unescape",
    ):
        return True
    return any(_calls_markdown_or_unescape(child) for child in node.get("children", []))


def _resolve_detail_description(
    truth: dict, document: dict | list
) -> tuple[str | None, dict | None]:
    """Resolve a detail truth reply's description: a named field, rendered once, or
    a transcription. Returns the description and the source to pin in
    expected.json, the latter None when the reply transcribed instead.
    """
    source = truth.get("description_source")
    if source is None:
        return truth.get("description"), None

    if not isinstance(source, dict):
        raise UnlearnablePage("description_source is not an object")
    field = source.get("field")
    if not isinstance(field, str):
        raise UnlearnablePage("description_source.field is not a string")
    html_escaped = source.get("html_escaped")
    if not isinstance(html_escaped, bool):
        raise UnlearnablePage("description_source.html_escaped is not a boolean")
    try:
        compiled = jmespath.compile(field)
    except jmespath.exceptions.JMESPathError as exc:
        raise UnlearnablePage(
            f"description_source.field does not compile: {exc}"
        ) from exc
    if _calls_markdown_or_unescape(compiled.parsed):
        raise UnlearnablePage(
            "description_source.field calls markdown or unescape, which would "
            "convert its result a second time"
        )
    try:
        value = evaluate_expression(field, document)
    except MappingError as exc:
        raise UnlearnablePage(
            f"description_source.field failed to evaluate: {exc}"
        ) from exc
    if not isinstance(value, str) or not value.strip():
        raise UnlearnablePage(
            "description_source.field did not select a non-blank string"
        )

    rendered = html.unescape(value) if html_escaped else value
    return html_to_markdown(rendered), source


def _learn_detail_mapping(
    model: LLMModel, domain: str, url: str, document: dict | list
) -> tuple[MappingNames, str]:
    names = _mapping_names(domain, "detail")
    text = json.dumps(document, indent=2)
    budget = budget_chars("detail")
    if len(text) > budget:
        # A detail document is never trimmed: its arrays are one posting's own
        # shape, not padding a trimmer could safely drop.
        raise UnlearnablePage(
            f"posting is {len(text)} chars, over the {budget}-char budget"
        )

    truth = parse_json_object(model.generate_mapping_expected("detail", text, url))
    if truth == {}:
        raise TruthAgentUnreadable("truth agent reply could not be parsed")

    description, description_source = _resolve_detail_description(truth, document)
    if (
        not _is_grounded_text(truth.get("title"))
        or not _is_grounded_text(truth.get("company_name"))
        or not _is_grounded_text(description)
    ):
        raise UnlearnablePage("truth agent grounded no title, company or description")

    expected = {
        field: truth[field]
        for field in _SILVER_FIELDS
        if field != "description" and field in truth
    }
    expected["description"] = description
    if description_source is not None:
        expected["description_source"] = description_source
    _write_mapping_snapshot(
        names, "detail.json", text, expected, "DetailMappingSnapshotTest"
    )
    _write_generated_mapping_document(names, model, "detail", domain, text)
    return names, model.model_name


def learn_mapping(
    model: LLMModel, domain: str, url: str, document: dict | list, mapping_type: str
) -> tuple[MappingNames, str]:
    """Generate a mapping for an API response or posting, test-first.

    Takes an already-parsed *document*, never a raw string: parsing and
    validating the body is `process_task`'s, before the lease.
    """
    if mapping_type == "index":
        return _learn_index_mapping(model, domain, url, document)
    if mapping_type == "detail":
        return _learn_detail_mapping(model, domain, url, document)
    raise ValueError(
        f"learn_mapping supports mapping_type 'index' or 'detail', got {mapping_type!r}"
    )
