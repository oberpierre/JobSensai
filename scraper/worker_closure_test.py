import os
import unittest
from pathlib import Path

# Each of these weighs tens of megabytes in an image and none is imported by a
# worker, so one reaching a worker's closure is a dependency edge to cut.
CRAWLER_ONLY = ("scrapy", "twisted", "playwright")


def _closure(name: str) -> list[str]:
    path = Path(os.environ["TEST_SRCDIR"], "_main", "scraper", name)
    return path.read_text().splitlines()


class TestWorkerClosures(unittest.TestCase):
    def test_worker_images_carry_no_crawler_dependency(self):
        for closure in ("worker_closure", "silver_worker_closure"):
            labels = _closure(closure)
            with self.subTest(closure=closure):
                self.assertTrue(labels, f"{closure} is empty")
                leaked = [
                    label
                    for label in labels
                    if any(package in label for package in CRAWLER_ONLY)
                ]
                self.assertEqual(leaked, [])


if __name__ == "__main__":
    unittest.main()
