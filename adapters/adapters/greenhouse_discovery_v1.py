from urllib.parse import urljoin

from bs4 import BeautifulSoup

from adapters.adapters.base import DiscoveryAdapter


class GreenhouseIOAdapter(DiscoveryAdapter):
    domains = ["job-boards.greenhouse.io", "greenhouse.io"]

    def get_job_links(self, html: str, url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        job_links = []

        # Look for job listings in the standard Greenhouse format
        # Usually job links are in <a> tags with href attributes
        for link in soup.find_all("a", href=True):
            href = link["href"]
            # Check if the link looks like a job posting URL
            if "/jobs/" in href and not href.startswith("#"):
                absolute_url = urljoin(url, href)
                job_links.append(absolute_url)

        # Also check for data attributes that might contain job URLs
        for job_element in soup.find_all(attrs={"data-job-url": True}):
            job_url = job_element.get("data-job-url")
            if job_url:
                absolute_url = urljoin(url, job_url)
                job_links.append(absolute_url)

        # Remove duplicates while preserving order
        seen = set()
        unique_links = []
        for link in job_links:
            if link not in seen:
                seen.add(link)
                unique_links.append(link)

        return unique_links

    def get_next_page_links(self, html: str, url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        next_page_links = []

        # Look for pagination links
        pagination_links = soup.find_all("a", href=True)
        for link in pagination_links:
            href = link["href"]
            text = link.get_text(strip=True).lower()

            # Common pagination indicators
            if any(indicator in text for indicator in ["next", ">", "»"]):
                absolute_url = urljoin(url, href)
                next_page_links.append(absolute_url)

        # Also check for data attributes related to pagination
        for element in soup.find_all(attrs={"data-next-page": True}):
            next_page_url = element.get("data-next-page")
            if next_page_url:
                absolute_url = urljoin(url, next_page_url)
                next_page_links.append(absolute_url)

        # Remove duplicates while preserving order
        seen = set()
        unique_links = []
        for link in next_page_links:
            if link not in seen:
                seen.add(link)
                unique_links.append(link)

        return unique_links
