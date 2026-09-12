# Extract the ground-truth snapshot for a $mapping_type API response

You are extracting the **ground truth** from a real job-board API response so an automated test can check a mapping against it. Read the response below and report exactly which posting URLs it carries.

## Task

List every job-posting URL the response carries.

## Output

Return **only** a JSON object: no prose, no explanation, no markdown fences.

{"job_links": ["<absolute url>", ...]}

Rules:

- URLs must be **absolute**. Resolve relative URLs against the response URL: `$url`.
- Return JSON only. No markdown fences.
- Report only what the response actually contains. Do not invent or guess values.
- Use an empty list when the response carries no posting URLs at all. Reply
  `{"job_links": []}`, never `{}` and never prose saying there are none.

## Response

$body
