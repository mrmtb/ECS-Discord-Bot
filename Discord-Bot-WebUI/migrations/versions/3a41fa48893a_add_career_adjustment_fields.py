"""Add career adjustment fields

Revision ID: 3a41fa48893a
Revises: 7f45bdaef5bc
Create Date: 2024-08-27 14:27:44.026787

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3a41fa48893a'
down_revision = '7f45bdaef5bc'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('player', schema=None) as batch_op:
        batch_op.add_column(sa.Column('career_goals_adjustment', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('career_assists_adjustment', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('career_yellow_cards_adjustment', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('career_red_cards_adjustment', sa.Integer(), nullable=True))
        batch_op.drop_column('career_assists_override')
        batch_op.drop_column('career_goals_override')
        batch_op.drop_column('career_red_cards_override')
        batch_op.drop_column('career_yellow_cards_override')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('player', schema=None) as batch_op:
        batch_op.add_column(sa.Column('career_yellow_cards_override', sa.INTEGER(), autoincrement=False, nullable=True))
        batch_op.add_column(sa.Column('career_red_cards_override', sa.INTEGER(), autoincrement=False, nullable=True))
        batch_op.add_column(sa.Column('career_goals_override', sa.INTEGER(), autoincrement=False, nullable=True))
        batch_op.add_column(sa.Column('career_assists_override', sa.INTEGER(), autoincrement=False, nullable=True))
        batch_op.drop_column('career_red_cards_adjustment')
        batch_op.drop_column('career_yellow_cards_adjustment')
        batch_op.drop_column('career_assists_adjustment')
        batch_op.drop_column('career_goals_adjustment')

    # ### end Alembic commands ###