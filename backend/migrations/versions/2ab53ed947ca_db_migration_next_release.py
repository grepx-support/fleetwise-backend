"""db migration released on Jan2026

Revision ID: 2ab53ed947ca
Revises: b8cdf76f6f19
Create Date: 2025-01-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2ab53ed947ca'
down_revision: Union[str, Sequence[str], None] = 'b8cdf76f6f19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add dropoff_time column to job table
    op.add_column('job', sa.Column('dropoff_time', sa.String(length=32), nullable=True))
    
    # Create table for driver leave overrides
    op.create_table('leave_override',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('driver_leave_id', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('override_date', sa.Date(), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=False),
    sa.Column('end_time', sa.Time(), nullable=False),
    sa.Column('override_reason', sa.String(length=512), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='0'),
    sa.ForeignKeyConstraint(['driver_leave_id'], ['driver_leave.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('driver_leave_id', 'override_date', 'start_time', 'end_time', name='uq_leave_override_no_duplicate')
    )
    op.create_index('idx_leave_override_leave_id', 'leave_override', ['driver_leave_id'], unique=False)
    op.create_index('idx_leave_override_date_time', 'leave_override', ['override_date', 'start_time', 'end_time'], unique=False)
    op.create_index('idx_leave_override_leave_date', 'leave_override', ['driver_leave_id', 'override_date'], unique=False)
    op.create_index('idx_leave_override_created_by', 'leave_override', ['created_by'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # Remove dropoff_time column from job table
    op.drop_column('job', 'dropoff_time')
    
    # Drop leave_override table
    op.drop_index('idx_leave_override_created_by', table_name='leave_override')
    op.drop_index('idx_leave_override_leave_date', table_name='leave_override')
    op.drop_index('idx_leave_override_date_time', table_name='leave_override')
    op.drop_index('idx_leave_override_leave_id', table_name='leave_override')
    op.drop_table('leave_override')
    # ### end Alembic commands ###

