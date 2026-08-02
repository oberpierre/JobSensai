import importlib
import os
import unittest
from unittest.mock import patch
from urllib.parse import quote

import scraper.database as database


class TestDatabaseUrlEncoding(unittest.TestCase):
    """DB_USER/DB_PASSWORD are read at import time, so credentials are exercised by
    reloading the module under a patched environment rather than by calling a
    function."""

    def setUp(self):
        # Restore module state computed from the real environment once each test's
        # patched environment goes out of scope, so later tests see defaults again.
        self.addCleanup(importlib.reload, database)

    def _reload_with_env(self, env: dict) -> str:
        with patch.dict(os.environ, env, clear=False):
            importlib.reload(database)
        return database.DATABASE_URL

    def test_encodes_special_characters_in_password(self):
        password = "unsafe@chars/in:this#value"
        url = self._reload_with_env({"POSTGRES_PASSWORD": password})

        self.assertNotIn(password, url)
        self.assertIn(quote(password, safe=""), url)

    def test_encodes_special_characters_in_user(self):
        user = "user@name"
        url = self._reload_with_env({"POSTGRES_USER": user})

        self.assertNotIn(f"{user}:", url)
        self.assertIn(f"{quote(user, safe='')}:", url)

    def test_plain_credentials_are_unchanged(self):
        url = self._reload_with_env(
            {"POSTGRES_USER": "jobsensai", "POSTGRES_PASSWORD": "devpass"}
        )

        self.assertIn("jobsensai:devpass@", url)


if __name__ == "__main__":
    unittest.main()
