"""Add foreign key to League

Revision ID: c7bc570f6ca6
Revises: b68cd4bb6445
Create Date: 2024-08-21 15:37:54.028213

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7bc570f6ca6'
down_revision = 'b68cd4bb6445'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('league', schema=None) as batch_op:
        batch_op.add_column(sa.Column('season_id', sa.Integer(), nullable=False))
        batch_op.create_foreign_key(None, 'season', ['season_id'], ['id'])

    with op.batch_alter_table('season', schema=None) as batch_op:
        batch_op.alter_column('name',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.String(length=100),
               existing_nullable=False)
        batch_op.drop_column('year')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('season', schema=None) as batch_op:
        batch_op.add_column(sa.Column('year', sa.INTEGER(), autoincrement=False, nullable=False))
        batch_op.alter_column('name',
               existing_type=sa.String(length=100),
               type_=sa.VARCHAR(length=50),
               existing_nullable=False)

    with op.batch_alter_table('league', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_column('season_id')

    # ### end Alembic commands ###