import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app


class TestHealth(unittest.TestCase):
    def setUp(self):
        os.environ.pop("WEB_DIST_DIR", None)
        self.client = TestClient(create_app())

    def test_health_returns_ok(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class TestMountSkippedWhenDistDirIsAbsent(unittest.TestCase):
    def test_app_still_serves_the_api_when_web_dist_dir_names_a_missing_directory(self):
        with patch.dict(os.environ, {"WEB_DIST_DIR": "/no/such/directory"}):
            client = TestClient(create_app())
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)

    def test_unset_web_dist_dir_also_skips_the_mount(self):
        os.environ.pop("WEB_DIST_DIR", None)
        client = TestClient(create_app())
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)


class TestMountSkippedWhenDistDirHasNoIndex(unittest.TestCase):
    def test_root_does_not_500_when_the_bundle_directory_is_empty(self):
        with (
            tempfile.TemporaryDirectory() as empty_dir,
            patch.dict(os.environ, {"WEB_DIST_DIR": empty_dir}),
        ):
            client = TestClient(create_app())
            response = client.get("/")
        self.assertEqual(response.status_code, 404)


class TestSpaMount(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        dist_dir = Path(self.tmpdir.name)
        (dist_dir / "index.html").write_text("<html>spa</html>")

        self.env_patcher = patch.dict(os.environ, {"WEB_DIST_DIR": str(dist_dir)})
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        self.client = TestClient(create_app())

    def test_index_is_served_at_root(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("spa", response.text)

    def test_unknown_client_side_route_falls_through_to_index(self):
        response = self.client.get("/jobs/some-uuid")
        self.assertEqual(response.status_code, 200)
        self.assertIn("spa", response.text)

    def test_unknown_api_route_stays_a_json_404(self):
        response = self.client.get("/api/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers["content-type"], "application/json")

    def test_a_path_merely_starting_with_api_falls_through_to_index(self):
        response = self.client.get("/apidocs")
        self.assertEqual(response.status_code, 200)
        self.assertIn("spa", response.text)


if __name__ == "__main__":
    unittest.main()
