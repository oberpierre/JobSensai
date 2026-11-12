import unittest

from adapters.adapters.snapshot import DetailMappingSnapshotTest


class TestBoardsApiGreenhouseIoDetailMapping(
    DetailMappingSnapshotTest, unittest.TestCase
):
    basename = "boards_api_greenhouse_io_detail_v1"
