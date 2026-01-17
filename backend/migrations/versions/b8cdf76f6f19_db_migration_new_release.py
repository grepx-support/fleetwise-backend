"""empty_migration

Revision ID: b8cdf76f6f19
Revises: 8537e815aa61
Create Date: 2026-01-06 09:25:45.413763

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = 'b8cdf76f6f19'
down_revision: Union[str, Sequence[str], None] = '8537e815aa61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create table for OTP storage with expiration
    op.create_table('otp_storage',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=128), nullable=False),
    sa.Column('otp', sa.String(length=6), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('used', sa.Boolean(), nullable=False, default=False),
    sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_otp_storage_email'), 'otp_storage', ['email'], unique=False)
    op.create_index(op.f('ix_otp_storage_otp'), 'otp_storage', ['otp'], unique=False)
    op.create_index(op.f('ix_otp_storage_expires_at'), 'otp_storage', ['expires_at'], unique=False)

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
    # Drop leave_override table
    op.drop_index('idx_leave_override_created_by', table_name='leave_override')
    op.drop_index('idx_leave_override_leave_date', table_name='leave_override')
    op.drop_index('idx_leave_override_date_time', table_name='leave_override')
    op.drop_index('idx_leave_override_leave_id', table_name='leave_override')
    op.drop_table('leave_override')

    # Drop OTP storage table
    op.drop_index(op.f('ix_otp_storage_expires_at'), table_name='otp_storage')
    op.drop_index(op.f('ix_otp_storage_otp'), table_name='otp_storage')
    op.drop_index(op.f('ix_otp_storage_email'), table_name='otp_storage')
    op.drop_table('otp_storage')
    # ### end Alembic commands ###

