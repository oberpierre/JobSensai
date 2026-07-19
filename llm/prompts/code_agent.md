# Implement the $adapter_type adapter `$adapter_class`

You are an expert Python web-scraping engineer. Implement the class `$adapter_class`,
inheriting `$base_class`, that parses the HTML shown below.

## Requirements

- Import the base class with exactly this line (no other base import):
  `from adapters.adapters.base import $base_class`
- $role_requirements
- Declare a class attribute: `domains = $domains`
- Use BeautifulSoup (`bs4`) with `html.parser`.
- An `href` may be relative OR already absolute — always resolve with `urljoin(url, href)`
  (a no-op on absolute URLs) and identify the links you want by a distinctive URL
  substring, never by a leading `/`.
- Never raise; return an empty list or empty dict when content is absent.
- **Parse the HTML — do not hardcode the expected values.**
$silver_schema
## Base class to inherit from

$base_code

## Cleaned page HTML

$cleaned_html

Output ONLY valid Python source for the adapter module. Do NOT use markdown fences.
