"""Update willing_to_referee column to Text

Revision ID: 988f5a6fe074
Revises: 2f2ff7ee77dd
Create Date: 2024-08-26 13:04:49.309530

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '988f5a6fe074'
down_revision = '2f2ff7ee77dd'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('player', schema=None) as batch_op:
        batch_op.alter_column('willing_to_referee',
               existing_type=sa.BOOLEAN(),
               type_=sa.Text(),
               existing_nullable=True)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('player', schema=None) as batch_op:
        batch_op.alter_column('willing_to_referee',
               existing_type=sa.Text(),
               type_=sa.BOOLEAN(),
               existing_nullable=True)

    # ### end Alembic commands ###