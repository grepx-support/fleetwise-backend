"""Add Ancillary Fields to Service Table

Revision ID: 3f5a004fa0c7
Revises: d1b5284f3617
Create Date: 2025-11-02 10:34:17.013305

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f5a004fa0c7'
down_revision: Union[str, Sequence[str], None] = 'd1b5284f3617'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add ancillary charge fields to service table
    op.add_column('service', sa.Column('is_ancillary', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('service', sa.Column('condition_type', sa.String(length=64), nullable=True))
    op.add_column('service', sa.Column('condition_config', sa.Text(), nullable=True))
    op.add_column('service', sa.Column('is_per_occurrence', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove ancillary charge fields from service table
    op.drop_column('service', 'is_per_occurrence')
    op.drop_column('service', 'condition_config')
    op.drop_column('service', 'condition_type')
    op.drop_column('service', 'is_ancillary')