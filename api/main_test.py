import os
import unittest
from unittest.mock import patch

from api.main import server_config


class TestServerConfig(unittest.TestCase):
    def test_defaults_to_port_8000_on_the_wildcard_host(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("API_PORT", None)
            host, port = server_config()
        self.assertEqual(host, "0.0.0.0")
        self.assertEqual(port, 8000)

    def test_api_port_overrides_the_default(self):
        with patch.dict(os.environ, {"API_PORT": "9001"}):
            _host, port = server_config()
        self.assertEqual(port, 9001)


if __name__ == "__main__":
    unittest.main()
