import unittest

from adapters.adapters import google_discovery_v1_test, google_extraction_v1_test


def load_tests(loader, tests, pattern):
    """Aggregate adapter test modules for the Bazel adapter_test target."""
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromModule(google_discovery_v1_test))
    suite.addTests(loader.loadTestsFromModule(google_extraction_v1_test))
    return suite


if __name__ == "__main__":
    unittest.main()
