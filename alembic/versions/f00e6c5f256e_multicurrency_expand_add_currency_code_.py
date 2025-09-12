"""multicurrency expand: add currency_code, widen to numeric(18,6), indexes

Revision ID: f00e6c5f256e
Revises: 2025_08_15_expense_categories_v2
Create Date: 2025-09-12 22:00:56.299679

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f00e6c5f256e'
down_revision: Union[str, None] = '2025_08_15_expense_categories_v2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
