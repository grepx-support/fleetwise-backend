"""add unique contraint in user table to customer and driver id 

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
        batch_op.create_unique_constraint('uq_user_customer_id', ['customer_id'])
        batch_op.create_unique_constraint('uq_user_driver_id', ['driver_id'])
    
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('contractor_service_pricing', schema=None) as batch_op:
        # Add vehicle_type_id column
        batch_op.add_column(sa.Column('vehicle_type_id', sa.Integer(), nullable=False))
        # Add foreign key constraint
        batch_op.create_foreign_key('fk_contractor_service_pricing_vehicle_type_id_vehicle_type', 'vehicle_type', ['vehicle_type_id'], ['id'], ondelete='CASCADE')
        # Create index
        batch_op.create_index(batch_op.f('ix_contractor_service_pricing_vehicle_type_id'), ['vehicle_type_id'], unique=False)
        # Add price column
        batch_op.add_column(sa.Column('price', sa.Float(), nullable=True))
        # Drop old unique constraint
        batch_op.drop_constraint('unique_contractor_service', type_='unique')
        # Create new unique constraint including vehicle_type_id
        batch_op.create_unique_constraint('unique_contractor_service_vehicle', ['contractor_id', 'service_id', 'vehicle_type_id'])


def downgrade() -> None:
    """Downgrade schema."""
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('user', schema=None) as batch_op:
        # Remove unique constraints
        batch_op.drop_constraint('uq_user_customer_id', type_='unique')
        batch_op.drop_constraint('uq_user_driver_id', type_='unique')
        # Remove name column
        batch_op.drop_column('name')
    
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('contractor_service_pricing', schema=None) as batch_op:
        # Drop new unique constraint
        batch_op.drop_constraint('unique_contractor_service_vehicle', type_='unique')
        # Recreate old unique constraint
        batch_op.create_unique_constraint('unique_contractor_service', ['contractor_id', 'service_id'])
        # Drop added columns
        batch_op.drop_index(batch_op.f('ix_contractor_service_pricing_vehicle_type_id'))
        batch_op.drop_constraint('fk_contractor_service_pricing_vehicle_type_id_vehicle_type', type_='foreignkey')
        batch_op.drop_column('vehicle_type_id')
        batch_op.drop_column('price')