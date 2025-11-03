"""Add Ancillary Charges Field to Job Table

Revision ID: 576a288c7216
Revises: 3f5a004fa0c7
Create Date: 2025-11-02 10:38:11.558053

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '576a288c7216'
down_revision: Union[str, Sequence[str], None] = '3f5a004fa0c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add ancillary_charges field to job table
    # Note: SQLite has limited ALTER TABLE support. If you encounter issues,
    # you may need to recreate the table or use a different approach.
    op.add_column('job', sa.Column('ancillary_charges', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove ancillary_charges field from job table
    # Note: SQLite has limited ALTER TABLE support for dropping columns.
    # This may require table recreation in SQLite environments.
    op.drop_column('job', 'ancillary_charges')