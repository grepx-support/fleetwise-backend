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
        batch_op.create_unique_constraint('uq_user_customer_id', ['customer_id'])
        batch_op.create_unique_constraint('uq_user_driver_id', ['driver_id'])


def downgrade() -> None:
    """Downgrade schema."""
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_constraint('uq_user_customer_id', type_='unique')
        batch_op.drop_constraint('uq_user_driver_id', type_='unique')