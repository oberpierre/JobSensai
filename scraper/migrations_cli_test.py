import importlib
import io
import os
import unittest
from contextlib import contextmanager, redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, patch

from alembic.config import Config
from alembic.util import CommandError

import scraper.migrations_cli as migrations_cli


class TestBuildConfig(unittest.TestCase):
    """Mirrors _run_migrations' construction, plus pinning the write location."""

    def test_wires_script_location_version_locations_and_path_separator(self):
        config = migrations_cli._build_config()

        self.assertEqual(
            config.get_main_option("script_location"),
            str(migrations_cli._MIGRATIONS_DIR),
        )
        self.assertEqual(
            config.get_main_option("version_locations"),
            str(migrations_cli._VERSIONS_DIR),
        )
        self.assertEqual(config.get_main_option("path_separator"), "os")


class TestVersionsDirResolution(unittest.TestCase):
    """BUILD_WORKSPACE_DIRECTORY is read at import time, so it's exercised by
    reloading the module under a patched environment, as database_test.py does
    for DATABASE_URL."""

    def setUp(self):
        self.addCleanup(importlib.reload, migrations_cli)

    def test_uses_build_workspace_directory_when_bazel_run_sets_it(self):
        with patch.dict(
            os.environ, {"BUILD_WORKSPACE_DIRECTORY": "/some/checkout"}, clear=False
        ):
            importlib.reload(migrations_cli)

        self.assertEqual(
            migrations_cli._VERSIONS_DIR,
            Path("/some/checkout/scraper/migrations/versions"),
        )

    def test_falls_back_to_the_repo_root_outside_bazel_run(self):
        env = dict(os.environ)
        env.pop("BUILD_WORKSPACE_DIRECTORY", None)
        with patch.dict(os.environ, env, clear=True):
            importlib.reload(migrations_cli)

        self.assertTrue(
            str(migrations_cli._VERSIONS_DIR).endswith("scraper/migrations/versions")
        )


class TestScratchDatabaseNaming(unittest.TestCase):
    def test_scratch_db_prefix_is_named_after_the_configured_database(self):
        self.assertEqual(
            migrations_cli._SCRATCH_DB_PREFIX,
            f"{migrations_cli.DB_NAME}_migrations_scratch",
        )

    def test_scratch_db_name_starts_with_the_prefix(self):
        self.assertTrue(
            migrations_cli._SCRATCH_DB_NAME.startswith(
                migrations_cli._SCRATCH_DB_PREFIX
            )
        )

    def test_scratch_db_name_is_unique_per_run(self):
        # Computed at import time, so a fresh import is a stand-in for a
        # second, concurrent run: they must never pick the same name.
        self.addCleanup(importlib.reload, migrations_cli)
        first_name = migrations_cli._SCRATCH_DB_NAME

        importlib.reload(migrations_cli)

        self.assertNotEqual(first_name, migrations_cli._SCRATCH_DB_NAME)

    def test_admin_and_scratch_urls_point_at_the_same_server(self):
        self.assertTrue(migrations_cli._ADMIN_DATABASE_URL.endswith("/postgres"))
        self.assertTrue(
            migrations_cli._SCRATCH_DATABASE_URL.endswith(
                f"/{migrations_cli._SCRATCH_DB_NAME}"
            )
        )


def _connection_cm(connection: MagicMock) -> MagicMock:
    cm = MagicMock(name="connect_cm")
    cm.__enter__.return_value = connection
    cm.__exit__.return_value = False
    return cm


class TestScratchDatabaseLifecycle(unittest.TestCase):
    """create_engine and command.upgrade are recording doubles, as
    database_test.py's TestInitDbMigrationLock uses for init_db, since the
    suite runs on SQLite and has no advisory locks or CREATE DATABASE."""

    def setUp(self):
        self.calls = []
        self.admin_connections = []
        self.scratch_connection = MagicMock(name="scratch_connection")
        # Empty by default: the ordinary run finds no leftovers to sweep.
        self.leftover_rows = []

        def fake_create_engine(url, *args, **kwargs):
            engine = MagicMock(name=f"engine({url})")
            if url == migrations_cli._ADMIN_DATABASE_URL:
                admin_connection = MagicMock(name="admin_connection")
                admin_connection.execution_options.return_value = admin_connection

                def admin_execute(stmt, params=None):
                    self.calls.append(("admin_execute", str(stmt)))
                    if stmt is migrations_cli._IDLE_LEFTOVERS_SQL:
                        return iter(self.leftover_rows)
                    return MagicMock()

                admin_connection.execute.side_effect = admin_execute
                self.admin_connections.append(admin_connection)
                engine.connect.return_value = _connection_cm(admin_connection)
            elif url == migrations_cli._SCRATCH_DATABASE_URL:
                engine.connect.return_value = _connection_cm(self.scratch_connection)
            return engine

        engine_patcher = patch.object(
            migrations_cli, "create_engine", side_effect=fake_create_engine
        )
        engine_patcher.start()
        self.addCleanup(engine_patcher.stop)

        upgrade_patcher = patch.object(
            migrations_cli.command,
            "upgrade",
            side_effect=lambda cfg, rev: self.calls.append(("upgrade", rev)),
        )
        upgrade_patcher.start()
        self.addCleanup(upgrade_patcher.stop)

    def test_sweeps_creates_upgrades_yields_and_drops_in_order(self):
        with migrations_cli._scratch_database() as config:
            self.assertIsInstance(config, Config)
            self.calls.append(("inside", None))

        steps = [step for step, _ in self.calls]
        self.assertEqual(
            steps,
            ["admin_execute", "admin_execute", "upgrade", "inside", "admin_execute"],
        )
        self.assertIn("pg_stat_activity", self.calls[0][1])
        self.assertIn(
            f'CREATE DATABASE "{migrations_cli._SCRATCH_DB_NAME}"', self.calls[1][1]
        )
        self.assertIn(
            f'DROP DATABASE IF EXISTS "{migrations_cli._SCRATCH_DB_NAME}"',
            self.calls[-1][1],
        )
        self.scratch_connection.commit.assert_called_once()

    def test_admin_connections_run_on_autocommit_isolation(self):
        with migrations_cli._scratch_database():
            pass

        self.assertEqual(len(self.admin_connections), 3)
        for admin_connection in self.admin_connections:
            admin_connection.execution_options.assert_called_once_with(
                isolation_level="AUTOCOMMIT"
            )

    def test_drops_the_scratch_database_even_when_the_body_raises(self):
        with self.assertRaises(RuntimeError), migrations_cli._scratch_database():
            raise RuntimeError("boom")

        steps = [step for step, _ in self.calls]
        self.assertEqual(steps[-1], "admin_execute")
        self.assertIn("DROP DATABASE", self.calls[-1][1])


class TestSweepLeftoverScratchDatabases(unittest.TestCase):
    """Exercises the sweep against a double naming its own live connections,
    since the suite runs on SQLite and has no pg_database or pg_stat_activity."""

    def _run_sweep(self, leftover_rows, execute_side_effect=None):
        calls = []
        admin_connection = MagicMock(name="admin_connection")
        admin_connection.execution_options.return_value = admin_connection

        def admin_execute(stmt, params=None):
            calls.append((str(stmt), params))
            if stmt is migrations_cli._IDLE_LEFTOVERS_SQL:
                return iter(leftover_rows)
            if execute_side_effect is not None:
                execute_side_effect(str(stmt))
            return MagicMock()

        admin_connection.execute.side_effect = admin_execute
        engine = MagicMock(name="engine")
        engine.connect.return_value = _connection_cm(admin_connection)

        with patch.object(migrations_cli, "create_engine", return_value=engine):
            migrations_cli._sweep_leftover_scratch_databases()

        return calls

    def test_queries_idle_databases_matching_the_scratch_prefix(self):
        calls = self._run_sweep(leftover_rows=[])

        query_stmt, query_params = calls[0]
        self.assertIn("pg_stat_activity", query_stmt)
        self.assertEqual(
            query_params, {"prefix": f"{migrations_cli._SCRATCH_DB_PREFIX}%"}
        )

    def test_drops_each_idle_leftover_the_query_names(self):
        calls = self._run_sweep(
            leftover_rows=[("jobsensai_migrations_scratch_abc123",)]
        )

        drop_stmts = [stmt for stmt, _ in calls if "DROP DATABASE" in stmt]
        self.assertEqual(
            drop_stmts,
            ['DROP DATABASE IF EXISTS "jobsensai_migrations_scratch_abc123"'],
        )

    def test_a_failed_drop_is_skipped_rather_than_aborting_the_sweep(self):
        def raise_on_leftover_one(stmt):
            if "leftover_one" in stmt:
                raise RuntimeError("another process connected to it")

        # Must not raise, and the second leftover's drop must still run.
        calls = self._run_sweep(
            leftover_rows=[("leftover_one",), ("leftover_two",)],
            execute_side_effect=raise_on_leftover_one,
        )

        drop_stmts = [stmt for stmt, _ in calls if "DROP DATABASE" in stmt]
        self.assertIn('DROP DATABASE IF EXISTS "leftover_two"', drop_stmts)


def _stub_scratch_database(config: Config):
    @contextmanager
    def _cm():
        yield config

    return _cm


class TestRunCheck(unittest.TestCase):
    def setUp(self):
        self.config = migrations_cli._build_config()
        patcher = patch.object(
            migrations_cli, "_scratch_database", _stub_scratch_database(self.config)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_zero_when_models_and_chain_agree(self):
        with patch.object(migrations_cli.command, "check"):
            self.assertEqual(migrations_cli._run_check(), 0)

    def test_returns_nonzero_and_names_the_diff_when_they_disagree(self):
        error = CommandError("New upgrade operations detected: company_size")
        with patch.object(migrations_cli.command, "check", side_effect=error):
            captured = io.StringIO()
            with redirect_stderr(captured):
                exit_code = migrations_cli._run_check()

        self.assertEqual(exit_code, 1)
        self.assertIn("company_size", captured.getvalue())


class TestRunRevision(unittest.TestCase):
    def setUp(self):
        self.config = migrations_cli._build_config()
        patcher = patch.object(
            migrations_cli, "_scratch_database", _stub_scratch_database(self.config)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_autogenerates_a_revision_with_the_given_message(self):
        with patch.object(migrations_cli.command, "revision") as mock_revision:
            migrations_cli._run_revision("add company size")

        mock_revision.assert_called_once_with(
            self.config, message="add company size", autogenerate=True
        )


class TestMain(unittest.TestCase):
    def test_revision_subcommand_dispatches_the_message(self):
        argv = ["migrations", "revision", "-m", "add company size"]
        with (
            patch.object(migrations_cli, "_run_revision") as mock_run_revision,
            patch("sys.argv", argv),
        ):
            migrations_cli.main()

        mock_run_revision.assert_called_once_with("add company size")

    def test_check_subcommand_exits_with_run_checks_return_code(self):
        argv = ["migrations", "check"]
        with (
            patch.object(
                migrations_cli, "_run_check", return_value=1
            ) as mock_run_check,
            patch("sys.argv", argv),
            self.assertRaises(SystemExit) as ctx,
        ):
            migrations_cli.main()

        mock_run_check.assert_called_once_with()
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
