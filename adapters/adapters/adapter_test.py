import importlib
import logging
import unittest
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_tests(
    loader: unittest.TestLoader, tests: unittest.TestSuite, pattern
) -> unittest.TestSuite:
    """Dynamically discover and load all adapter test modules."""
    suite = unittest.TestSuite()

    adapters_dir = Path(__file__).parent
    for test_file in sorted(adapters_dir.glob("*_test.py")):
        name = test_file.stem
        if name in ("adapter_test", "base_test", "snapshot_test", "_markdown_test"):
            continue
        module_name = f"adapters.adapters.{name}"
        try:
            module = importlib.import_module(module_name)
            logger.info(f"Loaded test module: {module_name}")
            suite.addTests(loader.loadTestsFromModule(module))
        except ImportError as exc:
            logger.warning(f"Warning: could not import {module_name}: {exc}")
    return suite


if __name__ == "__main__":
    unittest.main()
