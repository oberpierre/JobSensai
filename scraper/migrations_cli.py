"""CLI for authoring and validating Alembic migrations against a scratch
database built from the chain, never the developer's own. See README.md's
Database Migrations section for usage and behaviour.
"""

import argparse
import os
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.util import CommandError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from scraper.database import _MIGRATIONS_DIR, DATABASE_URL, DB_NAME

# Named after the configured database, not a fixed string, so two developers
# sharing one Postgres server, each with their own POSTGRES_DB, don't collide
# on one scratch database. The prefix is also the sweep's LIKE pattern, so a
# leftover from any past run under this Postgres database is found by name
# alone, regardless of the run-unique suffix it was created with.
_SCRATCH_DB_PREFIX = f"{DB_NAME}_migrations_scratch"

# Unique per run, not per database, so a crashed run's leftover can never
# collide with the name this run is about to create.
_SCRATCH_DB_NAME = f"{_SCRATCH_DB_PREFIX}_{uuid.uuid4().hex}"

_DB_SERVER_URL = DATABASE_URL.rsplit("/", 1)[0]
_ADMIN_DATABASE_URL = f"{_DB_SERVER_URL}/postgres"
_SCRATCH_DATABASE_URL = f"{_DB_SERVER_URL}/{_SCRATCH_DB_NAME}"

# A leftover has no open connection, whereas a concurrent run's own scratch
# database does, since it is still using it. Read against a double in
# migrations_cli_test.py, since the suite has no Postgres to run it against.
_IDLE_LEFTOVERS_SQL = text("""
    SELECT d.datname FROM pg_database d
    WHERE d.datname LIKE :prefix
      AND NOT EXISTS (SELECT 1 FROM pg_stat_activity a WHERE a.datname = d.datname)
""")

# Under `bazel run`, BUILD_WORKSPACE_DIRECTORY names the real checkout, whereas
# a revision written into the runfiles tree the binary executes from instead
# would be discarded the moment the run ends.
_WORKSPACE_ROOT = Path(
    os.environ.get(
        "BUILD_WORKSPACE_DIRECTORY", str(Path(__file__).resolve().parent.parent)
    )
)
_VERSIONS_DIR = _WORKSPACE_ROOT / "scraper" / "migrations" / "versions"


def _build_config() -> Config:
    """Same construction `_run_migrations` uses, so where migrations live is
    defined once, plus pinning where a new revision is written to the real
    checkout rather than wherever script_location's own default resolves to."""
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    config.set_main_option("version_locations", str(_VERSIONS_DIR))
    config.set_main_option("path_separator", "os")
    return config


def _sweep_leftover_scratch_databases() -> None:
    """Drop every idle database matching this run's scratch prefix, reclaiming
    what a `SIGKILL`, OOM kill or cancelled job left behind before `finally`
    could drop it. A database another process has just connected to between
    the listing query and this drop is left for that process's own cleanup:
    a failed drop is logged and skipped rather than raised.
    """
    engine = create_engine(_ADMIN_DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection = connection.execution_options(isolation_level="AUTOCOMMIT")
            leftovers = [
                row[0]
                for row in connection.execute(
                    _IDLE_LEFTOVERS_SQL, {"prefix": f"{_SCRATCH_DB_PREFIX}%"}
                )
            ]
            for datname in leftovers:
                try:
                    connection.execute(text(f'DROP DATABASE IF EXISTS "{datname}"'))
                except Exception as exc:
                    print(
                        f"Could not drop leftover scratch database {datname!r}: {exc}",
                        file=sys.stderr,
                    )
    finally:
        engine.dispose()


def _create_scratch_database() -> None:
    # CREATE DATABASE cannot run inside a transaction block, raising
    # ActiveSqlTransaction, so it goes out on an autocommit connection.
    engine = create_engine(_ADMIN_DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection = connection.execution_options(isolation_level="AUTOCOMMIT")
            connection.execute(text(f'CREATE DATABASE "{_SCRATCH_DB_NAME}"'))
    finally:
        engine.dispose()


def _drop_scratch_database() -> None:
    engine = create_engine(_ADMIN_DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection = connection.execution_options(isolation_level="AUTOCOMMIT")
            connection.execute(text(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB_NAME}"'))
    finally:
        engine.dispose()


def _upgrade_scratch_database(config: Config, connection: Connection) -> None:
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
    # Mirrors _run_migrations: begin_transaction() is a no-op on a connection
    # the caller already began, leaving the caller responsible for landing it.
    connection.commit()


@contextmanager
def _scratch_database():
    """Build a database from the migration chain and yield a Config wired to it.

    Swept before creation so a run that never reached its own `finally` does
    not block the next one. Dropped in `finally` too, so the ordinary case
    still leaves nothing behind for the sweep to find.
    """
    _sweep_leftover_scratch_databases()
    _create_scratch_database()
    try:
        engine = create_engine(_SCRATCH_DATABASE_URL)
        try:
            config = _build_config()
            with engine.connect() as connection:
                _upgrade_scratch_database(config, connection)
                yield config
        finally:
            engine.dispose()
    finally:
        _drop_scratch_database()


def _run_revision(message: str) -> None:
    with _scratch_database() as config:
        command.revision(config, message=message, autogenerate=True)


def _run_check() -> int:
    with _scratch_database() as config:
        try:
            command.check(config)
        except CommandError as exc:
            print(exc, file=sys.stderr)
            return 1
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Author and validate Alembic migrations against a scratch database."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    revision_parser = subparsers.add_parser(
        "revision", help="Autogenerate a new revision from the current models."
    )
    revision_parser.add_argument("-m", "--message", required=True)

    subparsers.add_parser(
        "check", help="Exit non-zero when the models and migrations disagree."
    )

    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()

    if args.command == "revision":
        _run_revision(args.message)
    else:
        sys.exit(_run_check())


if __name__ == "__main__":
    main()
