import os
from urllib.parse import quote

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scraper.models import Base

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


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
