"""add start_urls company_name

Lets an operator state a board's company once, on the row, so Silver can prefer it
over whatever a detail mapping or extraction adapter produced.

The `web` Deployment and the `crawler` CronJob never migrate, so from the moment
their new image starts until a worker has applied this revision, `/api/boards` and
a crawl fail on an undefined column.

Revision ID: d4f8a039fcb4
Revises: e61eeceef010
Create Date: 2026-09-13 09:39:48.546610

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4f8a039fcb4"
down_revision: Union[str, None] = "e61eeceef010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("start_urls", sa.Column("company_name", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("start_urls", "company_name")
