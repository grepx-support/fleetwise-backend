"""db migration released 15Jan2026

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
    
    # Create table for job monitoring alerts
    op.create_table('job_monitoring_alert',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('driver_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('reminder_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
    sa.Column('cleared_at', sa.DateTime(), nullable=True),
    sa.Column('last_reminder_at', sa.DateTime(), nullable=True),  # Track when last reminder was sent
    sa.ForeignKeyConstraint(['driver_id'], ['driver.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['job_id'], ['job.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_job_monitoring_alert_job_id'), 'job_monitoring_alert', ['job_id'], unique=False)
    op.create_index(op.f('ix_job_monitoring_alert_driver_id'), 'job_monitoring_alert', ['driver_id'], unique=False)
    op.create_index(op.f('ix_job_monitoring_alert_status'), 'job_monitoring_alert', ['status'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # Drop job monitoring alert table
    op.drop_index(op.f('ix_job_monitoring_alert_status'), table_name='job_monitoring_alert')
    op.drop_index(op.f('ix_job_monitoring_alert_driver_id'), table_name='job_monitoring_alert')
    op.drop_index(op.f('ix_job_monitoring_alert_job_id'), table_name='job_monitoring_alert')
    op.drop_table('job_monitoring_alert')
    
    # Drop OTP storage table
    op.drop_index(op.f('ix_otp_storage_expires_at'), table_name='otp_storage')
    op.drop_index(op.f('ix_otp_storage_otp'), table_name='otp_storage')
    op.drop_index(op.f('ix_otp_storage_email'), table_name='otp_storage')
    op.drop_table('otp_storage')
    # ### end Alembic commands ###