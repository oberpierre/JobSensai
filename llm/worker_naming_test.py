import unittest

from llm.worker import _adapter_names, _domain_slug


class TestDomainSlug(unittest.TestCase):
    def test_simple_domain(self):
        self.assertEqual(_domain_slug("www.google.com"), "www_google_com")

    def test_hyphenated_domain_is_a_valid_module_name(self):
        slug = _domain_slug("job-boards.greenhouse.io")
        self.assertEqual(slug, "job_boards_greenhouse_io")
        # The basename derived from the slug must import cleanly.
        self.assertTrue(f"{slug}_discovery_v1".isidentifier())

    def test_uppercase_is_normalised(self):
        self.assertEqual(_domain_slug("Google.COM"), "google_com")

    def test_no_leading_or_trailing_underscores(self):
        self.assertEqual(_domain_slug(".weird..domain."), "weird_domain")


class TestAdapterNames(unittest.TestCase):
    def test_simple_discovery(self):
        names = _adapter_names("google.com", "discovery")
        self.assertEqual(names.basename, "google_com_discovery_v1")
        self.assertEqual(names.adapter_class, "GoogleComDiscoveryAdapter")
        self.assertEqual(names.test_class, "TestGoogleComDiscoveryAdapter")
        self.assertEqual(names.module_path, f"adapters.adapters.{names.basename}")

    def test_hyphenated_extraction_with_version(self):
        names = _adapter_names("job-boards.greenhouse.io", "extraction", version=2)
        self.assertEqual(names.basename, "job_boards_greenhouse_io_extraction_v2")
        self.assertEqual(names.adapter_class, "JobBoardsGreenhouseIoExtractionAdapter")

    def test_names_are_valid_python_identifiers(self):
        names = _adapter_names("job-boards.greenhouse.io", "discovery")
        self.assertTrue(names.basename.isidentifier())
        self.assertTrue(names.adapter_class.isidentifier())
        self.assertTrue(names.test_class.isidentifier())


if __name__ == "__main__":
    unittest.main()
