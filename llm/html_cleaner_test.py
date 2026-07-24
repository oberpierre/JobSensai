import unittest

from llm.html_cleaner import clean_html


class TestCleanHtml(unittest.TestCase):
    def test_strips_noise_tags(self):
        html = (
            "<html><head><title>x</title></head><body>"
            "<script>evil()</script><style>.a{color:red}</style><svg></svg>"
            "<p>keep me</p></body></html>"
        )
        out = clean_html(html)
        self.assertNotIn("evil()", out)
        self.assertNotIn("color:red", out)
        self.assertNotIn("<svg", out)
        self.assertNotIn("<script", out)
        self.assertIn("keep me", out)

    def test_strips_comments(self):
        out = clean_html("<body><!-- secret --><p>hi</p></body>")
        self.assertNotIn("secret", out)
        self.assertIn("hi", out)

    def test_strips_data_uri_and_inline_style(self):
        html = (
            '<body><img src="data:image/png;base64,AAAABBBB">'
            '<a href="/jobs/1" style="color:red">Engineer</a></body>'
        )
        out = clean_html(html)
        self.assertNotIn("data:image", out)
        self.assertNotIn("color:red", out)
        self.assertIn("/jobs/1", out)

    def test_preserves_structure_and_returns_str(self):
        html = '<body><div class="job"><a href="/jobs/1">Engineer</a></div></body>'
        out = clean_html(html)
        self.assertIsInstance(out, str)
        self.assertIn("/jobs/1", out)
        self.assertIn("Engineer", out)
        self.assertIn("job", out)


if __name__ == "__main__":
    unittest.main()
