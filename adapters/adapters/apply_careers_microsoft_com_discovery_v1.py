from adapters.adapters.base import DiscoveryAdapter
from bs4 import BeautifulSoup
from urllib.parse import urljoin


class ApplyCareersMicrosoftComDiscoveryAdapter(DiscoveryAdapter):
    domains = ['apply.careers.microsoft.com']

    def get_job_links(self, html, url):
        soup = BeautifulSoup(html, 'html.parser')
        job_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            absolute_url = urljoin(url, href)
            if '/job/' in absolute_url and not absolute_url.endswith('/jobs/'):
                job_links.append(absolute_url)
        return job_links

    def get_next_page_links(self, html, url):
        soup = BeautifulSoup(html, 'html.parser')
        next_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            absolute_url = urljoin(url, href)
            if '/page/' in absolute_url and 'apply.careers.microsoft.com' in absolute_url:
                next_links.append(absolute_url)
        return next_links
