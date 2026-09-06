from adapters.adapters.base import DiscoveryAdapter
from bs4 import BeautifulSoup
from urllib.parse import urljoin


class WwwDatabricksComDiscoveryAdapter(DiscoveryAdapter):
    domains = ['www.databricks.com']

    def get_job_links(self, html, url):
        soup = BeautifulSoup(html, 'html.parser')
        job_links = []
        
        # Find all links that lead to job detail pages
        # These typically have a pattern like /jobs/ or /careers/...
        for link in soup.find_all('a', href=True):
            href = link['href']
            absolute_url = urljoin(url, href)
            
            # Check if the URL contains job-related patterns
            if ('/jobs/' in absolute_url or 
                '/careers/' in absolute_url and 
                'open-positions' not in absolute_url and
                'careers' in absolute_url and
                'company/careers' in absolute_url):
                # Ensure it's a job detail page (not a general careers page)
                if '/jobs/' in absolute_url or ('/careers/' in absolute_url and 
                                                'open-positions' not in absolute_url and
                                                'culture' not in absolute_url and
                                                'benefits' not in absolute_url and
                                                'diversity' not in absolute_url and
                                                'engineering' not in absolute_url and
                                                'research' not in absolute_url and
                                                'go-to-market' not in absolute_url and
                                                'interview-prep' not in absolute_url and
                                                'university-recruiting' not in absolute_url):
                    job_links.append(absolute_url)
        
        # Also look for links within the main content area that are likely job postings
        # The job listings seem to be in a specific section with data-cy="JobCard"
        job_cards = soup.find_all('a', href=True)
        for card in job_cards:
            href = card['href']
            absolute_url = urljoin(url, href)
            
            # Filter by URL patterns that indicate individual job postings
            if ('/jobs/' in absolute_url or 
                '/careers/' in absolute_url and 
                'open-positions' not in absolute_url and
                'company/careers' in absolute_url):
                # Additional filtering to avoid pagination links
                if ('/page/' not in absolute_url and
                    'department=' not in absolute_url and
                    'location=' not in absolute_url):
                    job_links.append(absolute_url)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_job_links = []
        for link in job_links:
            if link not in seen:
                seen.add(link)
                unique_job_links.append(link)
                
        return unique_job_links

    def get_next_page_links(self, html, url):
        soup = BeautifulSoup(html, 'html.parser')
        next_page_links = []
        
        # Look for pagination links
        pagination_links = soup.find_all('a', href=True)
        
        for link in pagination_links:
            href = link['href']
            absolute_url = urljoin(url, href)
            
            # Check if it's a pagination link (contains page number or next/prev)
            if ('page/' in absolute_url or 
                'next' in absolute_url.lower() or
                'previous' in absolute_url.lower() or
                'pagination' in absolute_url.lower()):
                # Make sure it's not a job detail link
                if '/jobs/' not in absolute_url and '/careers/' in absolute_url:
                    next_page_links.append(absolute_url)
        
        # Also check for links with specific pagination classes or data attributes
        pagination_elements = soup.find_all('a', {'data-cy': 'PaginationLink'})
        for element in pagination_elements:
            href = element.get('href')
            if href:
                absolute_url = urljoin(url, href)
                next_page_links.append(absolute_url)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_next_page_links = []
        for link in next_page_links:
            if link not in seen:
                seen.add(link)
                unique_next_page_links.append(link)
                
        return unique_next_page_links
