"""Rename match table to matches and update relationships

Revision ID: e15aa9d52a8e
Revises: 46194e31a3b4
Create Date: 2024-08-23 16:56:01.825176

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e15aa9d52a8e'
down_revision = '46194e31a3b4'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('matches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('time', sa.Time(), nullable=False),
    sa.Column('location', sa.String(length=100), nullable=False),
    sa.Column('home_team_id', sa.Integer(), nullable=False),
    sa.Column('away_team_id', sa.Integer(), nullable=False),
    sa.Column('home_team_score', sa.Integer(), nullable=True),
    sa.Column('away_team_score', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['away_team_id'], ['team.id'], ),
    sa.ForeignKeyConstraint(['home_team_id'], ['team.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('assist', schema=None) as batch_op:
        batch_op.drop_constraint('assist_match_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(None, 'matches', ['match_id'], ['id'])

    with op.batch_alter_table('goal', schema=None) as batch_op:
        batch_op.drop_constraint('goal_match_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(None, 'matches', ['match_id'], ['id'])

    with op.batch_alter_table('red_card', schema=None) as batch_op:
        batch_op.drop_constraint('red_card_match_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(None, 'matches', ['match_id'], ['id'])

    with op.batch_alter_table('yellow_card', schema=None) as batch_op:
        batch_op.drop_constraint('yellow_card_match_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(None, 'matches', ['match_id'], ['id'])

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('yellow_card', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key('yellow_card_match_id_fkey', 'schedule', ['match_id'], ['id'])

    with op.batch_alter_table('red_card', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key('red_card_match_id_fkey', 'schedule', ['match_id'], ['id'])

    with op.batch_alter_table('goal', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key('goal_match_id_fkey', 'schedule', ['match_id'], ['id'])

    with op.batch_alter_table('assist', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key('assist_match_id_fkey', 'schedule', ['match_id'], ['id'])

    op.drop_table('matches')
    # ### end Alembic commands ###