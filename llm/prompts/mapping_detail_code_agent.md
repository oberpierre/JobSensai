# Write the `jmespath` block for a detail mapping

You are an expert at JMESPath, a query language for JSON. Below is one job posting fetched from an API. Write the `jmespath` block of a mapping document that reads this posting into the Silver schema.

## Document shape

A finished mapping document looks like this:

```json
{"version": 1, "type": "detail", "domains": ["boards-api.example.com"],
 "jmespath": {"title": "title", "company_name": "company_name", "locations": "offices[].name",
 "description": "markdown(unescape(content))", "metadata": "{pay: pay_input_ranges}"}}
```

## Requirements

- Every value under `jmespath` is a JMESPath expression evaluated against the posting. The block may hold only `title`, `company_name`, `employment_type`, `locations`, `categories`, `description` and `metadata`. `title`, `company_name` and `description` are required: a posting missing one is refused. Omit any other key the posting does not state.
- `locations` and `categories` must each evaluate to a list of strings.
- Two functions exist beyond JMESPath's own. `unescape(s)` decodes HTML entities once, and `markdown(s)` converts HTML to markdown. `description` must be `markdown(...)` of the field holding the posting's description, wrapping it in `unescape(...)` first only when that field's markup is itself HTML-escaped.
- **`company_name` is never a string literal.** This document serves every company on the host it is registered under, so a literal would label all of them with one name.
- `version`, `type` and `domains` are written by the orchestrator, not by you. Do not include them. The domains this mapping serves: $domains

## Output

Return **only** `{"jmespath": {...}}`, with no prose and no markdown fences.

## Posting

$body
