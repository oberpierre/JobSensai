# Extract the ground-truth snapshot for one detail posting

You are extracting the **ground truth** from one job posting fetched from an API, as JSON, so an automated test can check a mapping against it. The posting below was fetched from `$url`. Report exactly what it states.

## Task

Report the posting's title, company, employment type, locations, categories, metadata, pay and its description. Where a field's type does not say what belongs in it, the field means exactly this:

$silver_field_definitions

## Output

Return **only** a JSON object: no prose, no explanation, no markdown fences.

{"title": "...", "company_name": "...", "employment_type": "... or null", "locations": ["..."], "categories": ["..."], "metadata": {}, "pay": {"min": <number or null>, "max": <number or null>, "currency": "...", "period": "..."} or null, "description_source": {"field": "...", "html_escaped": true}}

Give `"description": "..."` in place of `description_source` when the description is spread across several fields (see below).

## Rules

- `company_name` is the company the posting states. Omit it when the posting states none.
- Omit a metadata key whose value the posting leaves null or empty.
- Give pay as null when the posting states no pay amounts.
- **When one field of the posting holds the whole description, name it and do not transcribe it.** `field` is a JMESPath expression selecting that one string from the posting, and it must never call `markdown` or `unescape`. `html_escaped` is `true` when that field's markup is itself HTML-escaped, so a tag reads `&lt;p&gt;`, and `false` when it is raw HTML or plain text.
- **When the description is spread across several fields**, omit `description_source`. Render `description` as markdown instead: headings with `#`, lists as `-` or `1.`, paragraphs preserved, top heading at level 1 (`#`).
- Report only what the posting states. Do not invent or guess a value.
- Use an empty list when a list field has no values.

## Posting

$body
