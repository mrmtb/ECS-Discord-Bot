"""Multi-order fix

Revision ID: 812e5b6df6bd
Revises: f77382446ece
Create Date: 2024-08-28 15:46:12.022129

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '812e5b6df6bd'
down_revision = 'f77382446ece'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('player', schema=None) as batch_op:
        batch_op.add_column(sa.Column('needs_manual_review', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('linked_primary_player_id', sa.Integer(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('player', schema=None) as batch_op:
        batch_op.drop_column('linked_primary_player_id')
        batch_op.drop_column('needs_manual_review')

    # ### end Alembic commands ###