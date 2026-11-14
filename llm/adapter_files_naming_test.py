import unittest

from llm.adapter_files import _adapter_names, _domain_slug, _mapping_names, staged_paths


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


class TestMappingNames(unittest.TestCase):
    def test_index_mapping(self):
        names = _mapping_names("boards-api.greenhouse.io", "index")
        self.assertEqual(names.basename, "boards_api_greenhouse_io_index_v1")
        self.assertEqual(names.test_class, "TestBoardsApiGreenhouseIoIndexMapping")

    def test_detail_mapping(self):
        names = _mapping_names("boards-api.greenhouse.io", "detail")
        self.assertEqual(names.basename, "boards_api_greenhouse_io_detail_v1")
        self.assertEqual(names.test_class, "TestBoardsApiGreenhouseIoDetailMapping")

    def test_unknown_mapping_type_raises(self):
        with self.assertRaises(ValueError):
            _mapping_names("acme.com", "extraction")

    def test_never_falls_back_to_adapter_naming(self):
        # _adapter_names' type argument is free-form and falls back to
        # "extraction" for anything that is not "discovery", which would name a
        # mapping document as though it were an adapter.
        names = _mapping_names("acme.com", "index")
        self.assertNotIn("extraction", names.basename)


class TestStagedPaths(unittest.TestCase):
    def test_adapter_kind(self):
        paths = staged_paths("acme_com_discovery_v1", "adapter")
        self.assertEqual(
            paths,
            [
                "adapters/adapters/acme_com_discovery_v1.py",
                "adapters/adapters/acme_com_discovery_v1_test.py",
                "adapters/adapters/fixtures/acme_com_discovery_v1",
            ],
        )

    def test_mapping_kind(self):
        paths = staged_paths("acme_com_index_v1", "mapping")
        self.assertEqual(
            paths,
            [
                "adapters/adapters/mappings/acme_com_index_v1.json",
                "adapters/adapters/acme_com_index_v1_test.py",
                "adapters/adapters/fixtures/acme_com_index_v1",
            ],
        )

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            staged_paths("acme_com_index_v1", "extraction")


if __name__ == "__main__":
    unittest.main()
