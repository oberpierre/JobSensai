# Extract the ground-truth snapshot for a $adapter_type page

You are extracting the **ground truth** from a real job-board page so an automated test can
check an adapter against it. Read the cleaned HTML below and report exactly what is present.

## Task

$role_instructions

## Output

Return **only** a JSON object — no prose, no explanation, no markdown fences:

$output_shape

Rules:

- URLs must be **absolute**; resolve relative links against the page URL: `$url`.
- Report only what is actually on the page — do not invent or guess values.
- Use an empty list when a field has no values.

## Cleaned page HTML

$cleaned_html
