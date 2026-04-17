from adapters.adapters.base import ExtractionAdapter


class GoogleExtractionAdapter(ExtractionAdapter):
    """Extraction adapter for Google Careers."""

    def extract(self, html: str, url: str) -> dict:
        # TODO: Implement extraction logic for silver data lake
        return {}
