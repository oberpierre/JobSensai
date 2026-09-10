"""rename Bronze payload, add content_type and source_url

Bronze no longer holds only HTML: `html_content` is renamed to `raw_content`, and
`content_type` and `source_url` are added so a row records what it holds and where it
came from. The board type column's old value for an API board is rewritten to the new
one it renamed to. This rename is taken in one step rather than expand-contract: a pod
still running the previous release selects `html_content`, which this migration has
already dropped, and fails until it is redeployed onto the image that reads
`raw_content`.

Revision ID: 740a787aab69
Revises: 832e44da0602
Create Date: 2026-09-10 21:42:45.323738

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "740a787aab69"
down_revision: Union[str, None] = "832e44da0602"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A real rename, carrying every stored page forward. --autogenerate has no
    # notion of a rename and renders one as drop_column + add_column, which
    # discards the column's data instead.
    op.alter_column("raw_job_postings", "html_content", new_column_name="raw_content")

    # Added nullable first: the table already has rows, so NOT NULL would raise
    # NotNullViolation before the backfill below has a value to put in them.
    op.add_column(
        "raw_job_postings", sa.Column("content_type", sa.Text(), nullable=True)
    )
    op.add_column("raw_job_postings", sa.Column("source_url", sa.Text(), nullable=True))

    op.execute("UPDATE raw_job_postings SET content_type = 'text/html'")
    op.execute("UPDATE raw_job_postings SET source_url = url")

    op.alter_column("raw_job_postings", "content_type", nullable=False)
    op.alter_column("raw_job_postings", "source_url", nullable=False)

    # The code after this migration only knows the new value, so a row still
    # holding the old one would otherwise be silently unrecognised rather than
    # crawled.
    op.execute("UPDATE start_urls SET type = 'api' WHERE type = 'json_api'")


def downgrade() -> None:
    op.execute("UPDATE start_urls SET type = 'json_api' WHERE type = 'api'")
    op.drop_column("raw_job_postings", "source_url")
    op.drop_column("raw_job_postings", "content_type")
    op.alter_column("raw_job_postings", "raw_content", new_column_name="html_content")
