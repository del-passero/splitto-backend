"""add group_invite

Revision ID: 7b08661241e1
Revises: fcab50bc945c
Create Date: 2025-07-30 21:03:42.583175

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b08661241e1'
down_revision: Union[str, None] = 'fcab50bc945c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('group_invites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=False),
    sa.Column('token', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_group_invites_id'), 'group_invites', ['id'], unique=False)
    op.create_index(op.f('ix_group_invites_token'), 'group_invites', ['token'], unique=True)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_group_invites_token'), table_name='group_invites')
    op.drop_index(op.f('ix_group_invites_id'), table_name='group_invites')
    op.drop_table('group_invites')
    # ### end Alembic commands ###
