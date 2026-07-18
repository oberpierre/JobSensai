import unittest

from llm.dom import prune_to_links, resolve_hrefs


class TestResolveHrefs(unittest.TestCase):
    def test_resolves_relative_against_page_url(self):
        out = resolve_hrefs('<a href="/jobs/1">J</a>', "https://acme.com/careers")
        self.assertIn('href="https://acme.com/jobs/1"', out)

    def test_honors_base_href(self):
        html = (
            '<head><base href="https://acme.com/app/"></head>'
            '<body><a href="jobs/results/1">J</a></body>'
        )
        out = resolve_hrefs(html, "https://acme.com/app/results/")
        # Resolves against <base>, not the page URL, so the path is not doubled.
        self.assertIn('href="https://acme.com/app/jobs/results/1"', out)
        self.assertNotIn("results/results", out)


class TestPruneToLinks(unittest.TestCase):
    def test_keeps_links_with_containers_and_children(self):
        html = (
            "<html><body>"
            '<div class="jobs"><a href="/j/1"><span>Engineer</span></a></div>'
            '<div class="filler"><p>lots of prose, no links here</p></div>'
            "</body></html>"
        )
        lean = prune_to_links(html)
        self.assertIn('href="/j/1"', lean)
        self.assertIn("Engineer", lean)  # anchor's children preserved
        self.assertIn("jobs", lean)  # link's container preserved
        self.assertNotIn("filler", lean)  # link-free branch removed
        self.assertNotIn("lots of prose", lean)

    def test_drops_everything_when_no_links(self):
        lean = prune_to_links("<html><body><p>no links here</p></body></html>")
        self.assertNotIn("no links here", lean)


if __name__ == "__main__":
    unittest.main()
