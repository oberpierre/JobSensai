import unittest

from adapters.adapters.snapshot import DiscoverySnapshotTest
from adapters.adapters.www_databricks_com_discovery_v1 import WwwDatabricksComDiscoveryAdapter


class TestWwwDatabricksComDiscoveryAdapter(DiscoverySnapshotTest, unittest.TestCase):
    adapter_cls = WwwDatabricksComDiscoveryAdapter
    fixture_dir = "www_databricks_com_discovery_v1"
