import unittest

from bs4 import BeautifulSoup

from adapters.adapters._markdown import html_to_markdown


class TestHtmlToMarkdown(unittest.TestCase):
    def test_headings_relevel_shallowest_to_h1(self):
        md = html_to_markdown("<div><h3>Overview</h3><p>Body text.</p></div>")
        self.assertTrue(md.startswith("# Overview"), md)
        self.assertIn("Body text.", md)

    def test_heading_gaps_are_preserved_not_compressed(self):
        # h2/h4 -> #/### : shallowest becomes H1, but the source's gap is kept (not ##).
        lines = html_to_markdown("<div><h2>Top</h2><h4>Deep</h4></div>").splitlines()
        self.assertIn("# Top", lines)
        self.assertIn("### Deep", lines)
        self.assertNotIn("## Deep", lines)

    def test_h1_source_is_left_untouched(self):
        md = html_to_markdown("<div><h1>Title</h1></div>")
        self.assertTrue(md.startswith("# Title"), md)

    def test_plain_paragraphs_have_no_headings(self):
        md = html_to_markdown("<div><p>Alpha</p><p>Beta</p></div>")
        self.assertNotIn("#", md)
        self.assertIn("Alpha", md)
        self.assertIn("Beta", md)

    def test_unordered_list_uses_dash_bullets(self):
        md = html_to_markdown("<ul><li>a</li><li>b</li></ul>")
        self.assertIn("- a", md)
        self.assertIn("- b", md)

    def test_ordered_list_is_numbered(self):
        md = html_to_markdown("<ol><li>a</li><li>b</li></ol>")
        self.assertIn("1. a", md)
        self.assertIn("2. b", md)

    def test_inline_emphasis_is_kept(self):
        md = html_to_markdown("<p><strong>Bold</strong> and <em>it</em>.</p>")
        self.assertIn("**Bold**", md)
        self.assertIn("*it*", md)

    def test_images_are_dropped(self):
        md = html_to_markdown('<p>See <img src="x.png" alt="logo"/> here.</p>')
        self.assertNotIn("x.png", md)
        self.assertNotIn("![", md)
        self.assertIn("See", md)
        self.assertIn("here.", md)

    def test_links_are_kept(self):
        md = html_to_markdown('<p><a href="https://x.com/p">policy</a></p>')
        self.assertIn("[policy](https://x.com/p)", md)

    def test_accepts_a_bs4_tag(self):
        node = BeautifulSoup("<div><h3>X</h3></div>", "html.parser").find("div")
        self.assertTrue(html_to_markdown(node).startswith("# X"))


if __name__ == "__main__":
    unittest.main()
