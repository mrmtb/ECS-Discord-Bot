"""Add position to announcement

Revision ID: 2e6aad92b13f
Revises: cf44c2ed05e7
Create Date: 2024-09-14 12:52:52.956614

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2e6aad92b13f'
down_revision = 'cf44c2ed05e7'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('announcement', schema=None) as batch_op:
        batch_op.add_column(sa.Column('position', sa.Integer(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('announcement', schema=None) as batch_op:
        batch_op.drop_column('position')

    # ### end Alembic commands ###