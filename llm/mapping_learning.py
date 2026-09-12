"""Learn an index mapping from an API response, test-first, like a discovery adapter.

The document is data rather than code, so the two agents here write a JMESPath
`jmespath` block instead of Python: a truth agent grounds the posting URLs a
response carries, then a code agent writes the expression that finds them.
"""

import copy
import json

from llm.adapter_files import (
    MappingNames,
    _mapping_names,
    _write_mapping,
    _write_mapping_snapshot,
)
from llm.learning_errors import TruthAgentUnreadable, UnlearnablePage
from llm.model import LLMModel, index_num_ctx, parse_json_object, strip_code_fences

# Tokens reserved for the prompt scaffold around the body and the model's reply,
# subtracted from the context window before sizing the body to it.
_PROMPT_RESERVE_TOKENS = 4096

# JSON is denser per token than prose, so this deliberately underestimates rather
# than risk cutting a prompt mid-token.
_JSON_CHARS_PER_TOKEN = 2


def budget_chars() -> int:
    """The character budget a trimmed response must fit, sized to `index_num_ctx()`.

    The only place this arithmetic is written: `process_task` checks it is
    positive before taking a lease, and `learn_mapping` trims to it. Two copies
    would let the check guard a budget nothing trims to.
    """
    window = index_num_ctx()
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


def learn_mapping(
    model: LLMModel, domain: str, url: str, document: dict | list, mapping_type: str
) -> tuple[MappingNames, str]:
    """Generate an index mapping for an API response, test-first.

    Takes an already-parsed *document*, never a raw string: parsing and
    validating the body is `process_task`'s, before the lease.
    """
    names = _mapping_names(domain, mapping_type)
    trimmed, trimmed_text = _trim_to_budget(document, budget_chars())

    truth = parse_json_object(
        model.generate_mapping_expected(mapping_type, trimmed_text, url)
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

    code_reply = model.generate_mapping(mapping_type, trimmed_text, [domain])
    parsed_code = parse_json_object(strip_code_fences(code_reply))
    if parsed_code == {}:
        # A reviewer's question is what the model produced, not what could be
        # salvaged from it, so the unreadable reply is written verbatim.
        _write_mapping(names, code_reply)
    else:
        # Written over the model's reply, never under it: a model that invents a
        # hostname would otherwise produce a document that routes nothing.
        document_out = {
            **parsed_code,
            "version": 1,
            "type": mapping_type,
            "domains": [domain],
        }
        _write_mapping(names, json.dumps(document_out, indent=2))

    return names, model.model_name
