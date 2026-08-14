"""Extraction adapter for Google Careers job detail pages."""

from bs4 import BeautifulSoup, Tag

from adapters.adapters._markdown import html_to_markdown
from adapters.adapters.base import ExtractionAdapter

# Google obfuscates its class names, so these hashes are the only handles it offers.
_PANEL_CLASS = "DkhPwc"
_COMPANY_CLASS = "RP7SMd"
_LOCATION_CLASS = "r0wTof"
_EXPERIENCE_CLASS = "wVSTAb"
_ICON_CLASS = "google-material-icons"


class WwwGoogleComExtractionAdapter(ExtractionAdapter):
    """Reads the posting shown in the detail panel of a Google Careers results page."""

    domains: list[str] = ["www.google.com"]

    def extract(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        # The page keeps the results list beside the posting, and each of its cards
        # repeats the title, company and location markup of the posting it links to.
        # Everything here is therefore read from inside the detail panel.
        panel = soup.find("div", class_=_PANEL_CLASS)
        if not isinstance(panel, Tag):
            return {}

        description = self._description(panel)
        # Material icons render their own name as text, as in "place Singapore", so a
        # label reads back with the icon name attached unless the icons go first.
        for icon in panel.find_all("i", class_=_ICON_CLASS):
            icon.decompose()

        title = panel.find("h2")
        company = panel.find("span", class_=_COMPANY_CLASS)
        experience = panel.find("span", class_=_EXPERIENCE_CLASS)

        return {
            "title": title.get_text(strip=True) if title else "",
            "company_name": company.get_text(strip=True) if company else "",
            # Google states an experience level where the Silver schema wants an
            # employment type, so the level is reported as itself in metadata.
            "employment_type": None,
            "locations": self._locations(panel),
            "categories": [],
            "description": description,
            "metadata": (
                {"experience_level": experience.get_text(strip=True)}
                if experience
                else {}
            ),
        }

    def _description(self, panel: Tag) -> str:
        """Render the panel's prose sections, in page order, as one markdown block."""
        sections = []
        for section in panel.find_all("div", recursive=False):
            if not section.find("h3"):
                continue
            # A dismissible notice sits above the qualifications and is the only block
            # among these carrying an icon, which is what distinguishes it from prose.
            for child in section.find_all("div", recursive=False):
                if child.find("i", class_=_ICON_CLASS):
                    child.decompose()
            sections.append(str(section))
        return html_to_markdown("".join(sections))

    def _locations(self, panel: Tag) -> list[str]:
        """The posting's locations, one per entry, without Google's separators."""
        locations = []
        for element in panel.find_all("span", class_=_LOCATION_CLASS):
            location = element.get_text(strip=True).lstrip("; ").strip()
            if location:
                locations.append(location)
        return locations
