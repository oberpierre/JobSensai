import unittest

from adapters.adapters.snapshot import ExtractionSnapshotTest
from adapters.adapters.www_google_com_extraction_v1 import WwwGoogleComExtractionAdapter


class TestWwwGoogleComExtractionAdapter(ExtractionSnapshotTest, unittest.TestCase):
    adapter_cls = WwwGoogleComExtractionAdapter
    fixture_dir = "www_google_com_extraction_v1"
