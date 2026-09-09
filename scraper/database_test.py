import importlib
import os
import unittest
from unittest.mock import MagicMock, patch
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


class TestInitDbMigrationLock(unittest.TestCase):
    """SQLite has no pg_advisory_lock, so init_db's sequencing is proven against a
    recording double rather than a real database: _acquire_lock, _run_migrations and
    _release_lock are patched, and the test asserts the order they ran in and that
    each received the one connection init_db opened."""

    def setUp(self):
        self.connection = MagicMock(name="connection")
        engine_patcher = patch.object(database, "engine")
        mock_engine = engine_patcher.start()
        self.addCleanup(engine_patcher.stop)
        # A distinct object per call, so a second call to connect() would hand
        # _run_migrations a connection other than the one the lock was taken on,
        # and the identity assertion below would catch it.
        mock_engine.connect.side_effect = [self.connection, MagicMock(name="other")]

    def test_lock_taken_migration_committed_and_lock_released_in_order_on_same_conn(
        self,
    ):
        calls = []
        with (
            patch.object(
                database,
                "_acquire_lock",
                side_effect=lambda c: calls.append(("acquire", c)),
            ),
            patch.object(
                database,
                "_run_migrations",
                side_effect=lambda c: calls.append(("upgrade", c)),
            ),
            patch.object(
                database,
                "_release_lock",
                side_effect=lambda c: calls.append(("release", c)),
            ),
        ):
            self.connection.commit.side_effect = lambda: calls.append(
                ("commit", self.connection)
            )
            database.init_db()

        self.assertEqual(
            [step for step, _ in calls], ["acquire", "upgrade", "commit", "release"]
        )
        self.assertTrue(all(conn is self.connection for _, conn in calls))
        self.connection.close.assert_called_once()

    def test_upgrade_failure_still_releases_lock_and_propagates(self):
        with (
            patch.object(database, "_acquire_lock"),
            patch.object(database, "_run_migrations", side_effect=RuntimeError("boom")),
            patch.object(database, "_release_lock") as release,
            self.assertRaises(RuntimeError),
        ):
            database.init_db()

        release.assert_called_once_with(self.connection)
        self.connection.close.assert_called_once()
        # A failed migration leaves the connection's transaction aborted, so the
        # unlock immediately after would itself fail and mask the real error
        # unless init_db rolls back on that same connection first.
        self.connection.rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
