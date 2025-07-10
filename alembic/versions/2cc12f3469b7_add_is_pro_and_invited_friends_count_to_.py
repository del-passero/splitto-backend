"""Add is_pro and invited_friends_count to users, remove status from friends

Revision ID: 2cc12f3469b7
Revises: 6bb6e9e433e7
Create Date: 2025-07-10 19:48:35.993939

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2cc12f3469b7'
down_revision: Union[str, None] = '6bb6e9e433e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('users', sa.Column('is_pro', sa.Boolean(), nullable=False, server_default=sa.text('FALSE')))
    op.add_column('users', sa.Column('invited_friends_count', sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table('friends') as batch_op:
        batch_op.drop_column('status')

def downgrade():
    with op.batch_alter_table('friends') as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(), nullable=True))
    op.drop_column('users', 'invited_friends_count')
    op.drop_column('users', 'is_pro')
