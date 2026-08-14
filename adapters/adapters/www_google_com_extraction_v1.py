"""Extraction adapter for Google Careers job detail pages."""

from bs4 import BeautifulSoup, Tag

from adapters.adapters._markdown import html_to_markdown
from adapters.adapters.base import ExtractionAdapter

# Google obfuscates its class names, so these hashes are the only handles it offers.
_PANEL_CLASS = "DkhPwc"
_CHIP_ROW_CLASS = "op1BBf"
_LOCATION_CLASS = "r0wTof"
_LEVEL_CLASS = "wVSTAb"
_ICON_CLASS = "google-material-icons"

# The chips share one class, so each is identified by the icon that leads it.
_COMPANY_ICON = "corporate_fare"
_LOCATION_ICON = "place"
_LEVEL_ICON = "bar_chart"

_LOCATION_NOTE = "preferred working location from the following:"


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

        title = panel.find("h2")
        company = self._chip(panel, _COMPANY_ICON)
        level = self._level(panel)

        return {
            "title": title.get_text(strip=True) if title else "",
            "company_name": self._label(company) if company else "",
            # Google states an experience level where the Silver schema wants an
            # employment type, so the level is reported as itself in metadata.
            "employment_type": None,
            "locations": self._locations(panel),
            "categories": [],
            "description": self._description(panel),
            "metadata": {"experience_level": level} if level else {},
        }

    def _chip(self, panel: Tag, icon: str) -> Tag | None:
        """The chip in the summary row led by *icon*, or None when absent."""
        row = panel.find("div", class_=_CHIP_ROW_CLASS)
        if not isinstance(row, Tag):
            return None
        for chip in row.find_all(recursive=False):
            leading = chip.find("i", class_=_ICON_CLASS)
            if leading is not None and leading.get_text(strip=True) == icon:
                return chip
        return None

    def _label(self, chip: Tag) -> str:
        """A chip's text without its icon, whose ligature renders as its own name."""
        copy = BeautifulSoup(str(chip), "html.parser")
        for icon in copy.find_all("i", class_=_ICON_CLASS):
            icon.decompose()
        return copy.get_text(strip=True)

    def _level(self, panel: Tag) -> str:
        """The experience level, whose chip is a tooltip on some postings."""
        chip = self._chip(panel, _LEVEL_ICON)
        if chip is None:
            return ""
        named = chip.find("span", class_=_LEVEL_CLASS)
        return named.get_text(strip=True) if named else self._label(chip)

    def _locations(self, panel: Tag) -> list[str]:
        """Every location the posting offers, not only the ones the chip row shows.

        The chip row truncates to a "+N more" counter that omits the names entirely,
        whereas postings offering a choice restate the full list in a note above the
        qualifications. That note is preferred, so a truncated row costs nothing.
        """
        listed = self._location_note(panel)
        if listed:
            return listed

        chip = self._chip(panel, _LOCATION_ICON)
        if chip is None:
            return []
        locations = []
        for element in chip.find_all("span", class_=_LOCATION_CLASS):
            location = element.get_text(strip=True).lstrip("; ").strip()
            if location:
                locations.append(location)
        return locations

    def _location_note(self, panel: Tag) -> list[str]:
        """The locations the preferred-working-location note names, if it is shown."""
        marker = panel.find(string=lambda text: text and _LOCATION_NOTE in text)
        if marker is None or marker.parent is None:
            return []
        listed = marker.parent.get_text(" ", strip=True).split(_LOCATION_NOTE, 1)[1]
        return [name.strip(" .") for name in listed.split(";") if name.strip(" .")]

    def _description(self, panel: Tag) -> str:
        """Render the panel's prose sections, in page order, as one markdown block."""
        sections = []
        for section in panel.find_all("div", recursive=False):
            if not section.find("h3"):
                continue
            # Copied because the notice dropped below is where the locations are read
            # from, so removing it from the panel itself would empty that field.
            copy = BeautifulSoup(str(section), "html.parser").find("div")
            # A dismissible notice sits above the qualifications and is the only block
            # among these carrying an icon, which is what distinguishes it from prose.
            for child in copy.find_all("div", recursive=False):
                if child.find("i", class_=_ICON_CLASS):
                    child.decompose()
            sections.append(str(copy))
        return html_to_markdown("".join(sections))
