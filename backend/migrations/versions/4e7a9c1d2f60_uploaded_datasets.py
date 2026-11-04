"""uploaded datasets

Revision ID: 4e7a9c1d2f60
Revises: 8c41d7e2a6b3
Create Date: 2026-11-01 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4e7a9c1d2f60'
down_revision: Union[str, Sequence[str], None] = '8c41d7e2a6b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

Json = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        'datasets',
        sa.Column('key', sa.String(length=20), nullable=False),
        sa.Column('workspace_id', sa.String(length=32), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('data_class', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('summary', Json, nullable=False),
        sa.Column('created_by_id', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id']),
        sa.PrimaryKeyConstraint('key'),
    )
    op.create_table(
        'import_files',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('dataset_key', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=False),
        sa.Column('kind', sa.String(length=40), nullable=True),
        sa.Column('mapping', Json, nullable=False),
        sa.Column('timezone', sa.String(length=60), nullable=True),
        sa.Column('report', Json, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['dataset_key'], ['datasets.key'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_import_files_dataset_key'), 'import_files', ['dataset_key'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_import_files_dataset_key'), table_name='import_files')
    op.drop_table('import_files')
    op.drop_table('datasets')
