from adapters.adapters.base import ExtractionAdapter
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from adapters.adapters._markdown import html_to_markdown


class WwwGoogleComExtractionAdapter(ExtractionAdapter):
    domains = ['www.google.com']

    def extract(self, html, url):
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract title
        title_elem = soup.find('h2', class_='p1N2lc')
        title = title_elem.get_text(strip=True) if title_elem else ''
        
        # Extract company name
        company_elem = soup.find('span', class_='RP7SMd')
        company_name = company_elem.get_text(strip=True).split('\n')[0] if company_elem else ''
        
        # Extract locations
        location_elems = soup.find_all('span', class_='r0wTof')
        locations = [loc.get_text(strip=True) for loc in location_elems]
        
        # Extract employment type (experience level)
        exp_elem = soup.find('span', class_='wVSTAb')
        employment_type = exp_elem.get_text(strip=True) if exp_elem else None
        
        # Extract categories (from the job details section)
        categories = []
        # The categories are not explicitly listed in the HTML, so we'll leave this empty
        # as per the requirement to only extract what's stated on the page
        
        # Extract description
        # Find the main content div that contains the job description
        description_div = soup.find('div', class_='aG5W3')
        if description_div:
            # Remove share bars, related jobs, etc.
            for elem in description_div.find_all():
                if elem.name == 'div' and elem.get('class') and 'KwJkGe' in elem.get('class'):
                    elem.decompose()
                if elem.name == 'div' and elem.get('class') and 'bE3reb' in elem.get('class'):
                    elem.decompose()
                if elem.name == 'div' and elem.get('class') and 'fe9XXb' in elem.get('class'):
                    elem.decompose()
                if elem.name == 'div' and elem.get('class') and 'BDNOWe' in elem.get('class'):
                    elem.decompose()
                if elem.name == 'div' and elem.get('class') and 'KwJkGe' in elem.get('class'):
                    elem.decompose()
            description = html_to_markdown(description_div)
        else:
            description = ''
        
        # Extract metadata
        metadata = {}
        
        # Find all links and resolve them
        for link in soup.find_all('a', href=True):
            if 'google.com' in link['href']:
                resolved_href = urljoin(url, link['href'])
                link['href'] = resolved_href
        
        return {
            'title': title,
            'company_name': company_name,
            'employment_type': employment_type,
            'locations': locations,
            'categories': categories,
            'description': description,
            'metadata': metadata
        }
