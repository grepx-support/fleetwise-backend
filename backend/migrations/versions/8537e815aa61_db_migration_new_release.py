"""db_migration_new_release

Revision ID: 8537e815aa61
Revises: d1b5284f3617
Create Date: 2025-11-16 23:11:49.990822

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8537e815aa61'
down_revision: Union[str, Sequence[str], None] = 'd1b5284f3617'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create driver_leave table for driver leave management
    op.create_table(
        'driver_leave',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('driver_id', sa.Integer(), nullable=False),
        sa.Column('leave_type', sa.String(length=32), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),  # Changed from String to Date
        sa.Column('end_date', sa.Date(), nullable=False),    # Changed from String to Date
        sa.Column('status', sa.String(length=32), nullable=False, server_default='approved'),
        sa.Column('reason', sa.String(length=512), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(['driver_id'], ['driver.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    # Create indexes for performance
    op.create_index(op.f('ix_driver_leave_driver_id'), 'driver_leave', ['driver_id'], unique=False)
    op.create_index(op.f('ix_driver_leave_start_date'), 'driver_leave', ['start_date'], unique=False)
    op.create_index(op.f('ix_driver_leave_end_date'), 'driver_leave', ['end_date'], unique=False)
    # Additional performance indexes
    op.create_index('idx_driver_leave_driver_status', 'driver_leave', ['driver_id', 'status'], unique=False)
    op.create_index('idx_driver_leave_dates', 'driver_leave', ['start_date', 'end_date'], unique=False)
    op.create_index('idx_driver_leave_driver_dates', 'driver_leave', ['driver_id', 'start_date', 'end_date'], unique=False)
    op.create_index('idx_driver_leave_status', 'driver_leave', ['status'], unique=False)

    # Create job_reassignment table for job reassignment audit trail
    op.create_table(
        'job_reassignment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('driver_leave_id', sa.Integer(), nullable=False),
        sa.Column('original_driver_id', sa.Integer(), nullable=True),
        sa.Column('original_vehicle_id', sa.Integer(), nullable=True),
        sa.Column('original_contractor_id', sa.Integer(), nullable=True),
        sa.Column('new_driver_id', sa.Integer(), nullable=True),
        sa.Column('new_vehicle_id', sa.Integer(), nullable=True),
        sa.Column('new_contractor_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=512), nullable=True),
        sa.Column('reassigned_by', sa.Integer(), nullable=True),
        sa.Column('reassigned_at', sa.DateTime(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(['job_id'], ['job.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['driver_leave_id'], ['driver_leave.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['original_driver_id'], ['driver.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['original_vehicle_id'], ['vehicle.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['original_contractor_id'], ['contractor.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['new_driver_id'], ['driver.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['new_vehicle_id'], ['vehicle.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['new_contractor_id'], ['contractor.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reassigned_by'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_job_reassignment_job_id'), 'job_reassignment', ['job_id'], unique=False)
    op.create_index(op.f('ix_job_reassignment_driver_leave_id'), 'job_reassignment', ['driver_leave_id'], unique=False)
    # Additional performance indexes
    op.create_index('idx_job_reassignment_job', 'job_reassignment', ['job_id'], unique=False)
    op.create_index('idx_job_reassignment_leave', 'job_reassignment', ['driver_leave_id'], unique=False)

    # Add composite index on job table for driver leave queries
    # This improves performance when searching for jobs by driver and date range
    op.create_index('idx_job_driver_pickup_date', 'job', ['driver_id', 'pickup_date'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop composite index on job table
    op.drop_index('idx_job_driver_pickup_date', table_name='job')

    # Drop driver leave management tables and indexes
    # Drop job_reassignment indexes
    op.drop_index('idx_job_reassignment_leave', table_name='job_reassignment')
    op.drop_index('idx_job_reassignment_job', table_name='job_reassignment')
    op.drop_index(op.f('ix_job_reassignment_driver_leave_id'), table_name='job_reassignment')
    op.drop_index(op.f('ix_job_reassignment_job_id'), table_name='job_reassignment')
    op.drop_table('job_reassignment')

    # Drop driver_leave indexes
    op.drop_index('idx_driver_leave_status', table_name='driver_leave')
    op.drop_index('idx_driver_leave_driver_dates', table_name='driver_leave')
    op.drop_index('idx_driver_leave_dates', table_name='driver_leave')
    op.drop_index('idx_driver_leave_driver_status', table_name='driver_leave')
    op.drop_index(op.f('ix_driver_leave_end_date'), table_name='driver_leave')
    op.drop_index(op.f('ix_driver_leave_start_date'), table_name='driver_leave')
    op.drop_index(op.f('ix_driver_leave_driver_id'), table_name='driver_leave')
    op.drop_table('driver_leave')

    # ### end Alembic commands ###
