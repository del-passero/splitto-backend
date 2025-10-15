"""merge friends_cleanup + events_enhancements

Revision ID: e73e730d69b2
Revises: 20251016_friends_cleanup, 20251016_events_enhancements
Create Date: 2025-10-16 01:11:23.596083

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e73e730d69b2'
down_revision: Union[str, None] = ('20251016_friends_cleanup', '20251016_events_enhancements')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
