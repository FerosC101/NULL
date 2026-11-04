"""report versions and target dates

Revision ID: 8c41d7e2a6b3
Revises: 2642fefb1f47
Create Date: 2026-11-01 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8c41d7e2a6b3'
down_revision: Union[str, Sequence[str], None] = '2642fefb1f47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('remediations', sa.Column('target_date', sa.Date(), nullable=True))
    op.add_column('reports', sa.Column('version', sa.Integer(), server_default='1', nullable=False))
    # Reports that already exist are numbered in the order they were generated.
    op.execute(
        """
        UPDATE reports SET version = numbered.position
        FROM (
            SELECT id, row_number() OVER (PARTITION BY investigation_id ORDER BY created_at) AS position
            FROM reports
        ) AS numbered
        WHERE reports.id = numbered.id
        """
    )


def downgrade() -> None:
    op.drop_column('reports', 'version')
    op.drop_column('remediations', 'target_date')
