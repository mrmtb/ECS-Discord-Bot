"""Add has_completed_onboarding to User model

Revision ID: 244df0190bca
Revises: c168c2ccee29
Create Date: 2024-09-12 16:17:05.128048

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '244df0190bca'
down_revision = 'c168c2ccee29'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('has_completed_onboarding', sa.Boolean(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('has_completed_onboarding')

    # ### end Alembic commands ###