import unittest

from adapters.adapters.snapshot import IndexMappingSnapshotTest


class TestBoardsApiGreenhouseIoIndexMapping(
    IndexMappingSnapshotTest, unittest.TestCase
):
    basename = "boards_api_greenhouse_io_index_v1"
