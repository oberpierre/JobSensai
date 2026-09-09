import os
from pathlib import Path
from urllib.parse import quote

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

DB_USER = os.getenv("POSTGRES_USER", "jobsensai")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "jobsensaipassword")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "jobsensai")

# A generated password containing '@', '/', ':' or '#' would otherwise be
# misparsed as URL structure rather than credential content.
_DB_USER_ENCODED = quote(DB_USER, safe="")
_DB_PASSWORD_ENCODED = quote(DB_PASSWORD, safe="")

DATABASE_URL = (
    f"postgresql://{_DB_USER_ENCODED}:{_DB_PASSWORD_ENCODED}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# A literal constant, not a hash of a name: hash() is salted per process, so two
# workers would take two different locks, both acquire immediately, and migrate
# at the same time.
_MIGRATION_LOCK_KEY = 92_233_720

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_LOCK_SQL = text("SELECT pg_advisory_lock(:key)")
_UNLOCK_SQL = text("SELECT pg_advisory_unlock(:key)")


def _acquire_lock(connection) -> None:
    connection.execute(_LOCK_SQL, {"key": _MIGRATION_LOCK_KEY})


def _release_lock(connection) -> None:
    connection.execute(_UNLOCK_SQL, {"key": _MIGRATION_LOCK_KEY})


def _run_migrations(connection) -> None:
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    # Hands Alembic the connection the lock was taken on: opening its own from
    # the engine would migrate on a different connection than the one locked.
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


def init_db():
    connection = engine.connect()
    try:
        _acquire_lock(connection)
        try:
            _run_migrations(connection)
        except Exception:
            # A failed migration leaves the connection's transaction aborted, and
            # the unlock below is a further statement on that same connection, so
            # it would otherwise fail too and mask the migration's own error.
            connection.rollback()
            raise
        finally:
            _release_lock(connection)
    finally:
        connection.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
