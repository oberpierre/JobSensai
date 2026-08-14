import unittest

from adapters.adapters.snapshot import ExtractionSnapshotTest
from adapters.adapters.www_google_com_extraction_v1 import WwwGoogleComExtractionAdapter


class TestWwwGoogleComExtractionAdapter(ExtractionSnapshotTest, unittest.TestCase):
    adapter_cls = WwwGoogleComExtractionAdapter
    fixture_dir = "www_google_com_extraction_v1"

    def test_experience_level_is_reported_in_metadata(self):
        # The snapshot compares no metadata, so the level needs asserting here.
        self.assertEqual(self.data["metadata"], {"experience_level": "Mid"})


class TestWwwGoogleComExtractionAdapterMultiLocation(
    ExtractionSnapshotTest, unittest.TestCase
):
    """A posting whose summary row truncates its locations to a "+N more" counter."""

    adapter_cls = WwwGoogleComExtractionAdapter
    fixture_dir = "www_google_com_extraction_v1_multi_location"

    def test_experience_level_is_reported_in_metadata(self):
        # This posting's level chip carries the same class as its company chip, so a
        # lookup by class rather than by icon returns the company name here.
        self.assertEqual(self.data["metadata"], {"experience_level": "Director+"})
