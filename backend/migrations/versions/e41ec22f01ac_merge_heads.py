"""merge heads

Revision ID: e41ec22f01ac
Revises: d1b5284f3617
Create Date: 2025-10-31 23:53:43.672306

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e41ec22f01ac'
down_revision: Union[str, Sequence[str], None] = 'd1b5284f3617'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass