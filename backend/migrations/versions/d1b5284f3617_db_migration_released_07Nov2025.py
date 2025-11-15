"""db migration released on 07Nov2025

Revision ID: d1b5284f3617
Revises: 3da07bea5123
Create Date: 2025-10-31 08:16:34.411015

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1b5284f3617'
down_revision: Union[str, Sequence[str], None] = '3da07bea5123'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('user', schema=None) as batch_op:
        # Add name column to user table
        batch_op.add_column(sa.Column('name', sa.String(length=255), nullable=True))
        # Add unique constraints
        batch_op.create_unique_constraint('uq_user_driver_id', ['driver_id'])
        
    # Add ancillary charge fields to service table
    op.add_column('service', sa.Column('is_ancillary', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('service', sa.Column('condition_type', sa.String(length=64), nullable=True))
    op.add_column('service', sa.Column('condition_config', sa.Text(), nullable=True))
    op.add_column('service', sa.Column('is_per_occurrence', sa.Boolean(), nullable=False, server_default=sa.false()))

    
    # Use batch mode for SQLite compatibility
    # First, add vehicle_type_id as nullable
    with op.batch_alter_table('contractor_service_pricing', schema=None) as batch_op:
        batch_op.add_column(sa.Column('vehicle_type_id', sa.Integer(), nullable=True))
        # Add foreign key constraint
        batch_op.create_foreign_key('fk_contractor_service_pricing_vehicle_type_id_vehicle_type', 'vehicle_type', ['vehicle_type_id'], ['id'], ondelete='CASCADE')
        # Create index
        batch_op.create_index(batch_op.f('ix_contractor_service_pricing_vehicle_type_id'), ['vehicle_type_id'], unique=False)
        # Drop old unique constraint
        batch_op.drop_constraint('unique_contractor_service', type_='unique')
        # Create new unique constraint including vehicle_type_id
        batch_op.create_unique_constraint('unique_contractor_service_vehicle', ['contractor_id', 'service_id', 'vehicle_type_id'])
    
    # Backfill existing rows with default value (1 for E-Class Sedan)
    op.execute("UPDATE contractor_service_pricing SET vehicle_type_id = 1 WHERE vehicle_type_id IS NULL")
    
    # Then alter to non-nullable in new batch operation
    with op.batch_alter_table('contractor_service_pricing', schema=None) as batch_op:
        batch_op.alter_column('vehicle_type_id', nullable=False)

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
        sa.Column('reassignment_type', sa.String(length=32), nullable=False),
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
    op.create_index('idx_job_reassignment_type', 'job_reassignment', ['reassignment_type'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop driver leave management tables and indexes
    # Drop job_reassignment indexes
    op.drop_index('idx_job_reassignment_type', table_name='job_reassignment')
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

    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('user', schema=None) as batch_op:
        # Remove unique constraints
        batch_op.drop_constraint('uq_user_driver_id', type_='unique')
        # Remove name column
        batch_op.drop_column('name')
        # Remove ancillary charge fields from service table
    op.drop_column('service', 'is_per_occurrence')
    op.drop_column('service', 'condition_config')
    op.drop_column('service', 'condition_type')
    op.drop_column('service', 'is_ancillary')
    
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('contractor_service_pricing', schema=None) as batch_op:
        # Drop new unique constraint
        batch_op.drop_constraint('unique_contractor_service_vehicle', type_='unique')
    
    # Before recreating old constraint, remove duplicates by keeping only one row per contractor_id/service_id combination
    op.execute("""
        DELETE FROM contractor_service_pricing 
        WHERE id NOT IN (
            SELECT MIN(id) 
            FROM contractor_service_pricing 
            GROUP BY contractor_id, service_id
        )
    """)
    
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('contractor_service_pricing', schema=None) as batch_op:
        # Recreate old unique constraint
        batch_op.create_unique_constraint('unique_contractor_service', ['contractor_id', 'service_id'])
        # Drop added columns
        batch_op.drop_index(batch_op.f('ix_contractor_service_pricing_vehicle_type_id'))
        batch_op.drop_constraint('fk_contractor_service_pricing_vehicle_type_id_vehicle_type', type_='foreignkey')
        batch_op.drop_column('vehicle_type_id')