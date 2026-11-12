import importlib
import logging
import os
import unittest
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

_ADAPTERS_DIR = Path(__file__).parent
_NOT_ADAPTER_TESTS = ("adapter_test", "base_test", "snapshot_test", "_markdown_test")


def _failure(message: str) -> unittest.TestCase:
    """A test that fails with *message*."""

    def fail() -> None:
        raise AssertionError(message)

    return unittest.FunctionTestCase(fail)


def load_tests(
    loader: unittest.TestLoader, tests: unittest.TestSuite, pattern
) -> unittest.TestSuite:
    """Load every adapter test module, or only the one --test_filter names."""
    suite = unittest.TestSuite()
    only = os.environ.get("TESTBRIDGE_TEST_ONLY", "")
    candidates = [
        stem
        for stem in sorted(p.stem for p in _ADAPTERS_DIR.glob("*_test.py"))
        if stem not in _NOT_ADAPTER_TESTS
    ]

    if only and only not in candidates:
        suite.addTest(_failure(f"--test_filter={only} matched no adapter test module"))
        return suite

    for name in [only] if only else candidates:
        module_name = f"adapters.adapters.{name}"
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            if only:
                suite.addTest(_failure(f"could not import {module_name}: {exc}"))
            else:
                logger.warning(f"Warning: could not import {module_name}: {exc}")
            continue
        logger.info(f"Loaded test module: {module_name}")
        suite.addTests(loader.loadTestsFromModule(module))
    return suite


if __name__ == "__main__":
    unittest.main()
