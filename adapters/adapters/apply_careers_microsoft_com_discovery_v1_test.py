import unittest

from adapters.adapters.snapshot import DiscoverySnapshotTest
from adapters.adapters.apply_careers_microsoft_com_discovery_v1 import ApplyCareersMicrosoftComDiscoveryAdapter


class TestApplyCareersMicrosoftComDiscoveryAdapter(DiscoverySnapshotTest, unittest.TestCase):
    adapter_cls = ApplyCareersMicrosoftComDiscoveryAdapter
    fixture_dir = "apply_careers_microsoft_com_discovery_v1"
