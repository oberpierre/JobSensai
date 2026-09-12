# Write the `jmespath` block for a $mapping_type mapping

You are an expert at JMESPath, a query language for JSON. Below is a real job-board API response. Write the `jmespath` block of a mapping document that finds every posting in it.

## Document shape

A finished mapping document looks like this:

```json
{
  "version": 1,
  "type": "index",
  "domains": ["boards-api.example.com"],
  "jmespath": {
    "postings": "jobs[]",
    "job_url": "absolute_url"
  }
}
```

Every value under `jmespath` is a JMESPath expression. `postings` is evaluated against the whole response and must select the list of posting elements. `job_url` is evaluated against one posting element and must select that posting's URL.

## Requirements

- `postings` and `job_url` are both required, and they are the only keys your reply may hold.
- `version`, `type` and `domains` are written by the orchestrator, not by you. Do not include them. Anything you put there is discarded.
- The domains this mapping will serve: $domains

## Output

Return **only** a JSON object, in exactly this shape, with no prose and no markdown fences:

{"jmespath": {"postings": "...", "job_url": "..."}}

## Response

$body
