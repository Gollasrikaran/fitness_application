"""add personal_bests table and activity_logs.extraordinary column

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'activity_logs',
        sa.Column('extraordinary', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.create_check_constraint(
        'log_extraordinary_implies_implausible', 'activity_logs',
        'NOT extraordinary OR implausible',
    )

    op.create_table(
        'personal_bests',
        sa.Column('id', postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column('activity_type', sa.String(length=64), nullable=False),
        sa.Column('value', sa.Numeric(10, 2), nullable=False),
        sa.Column('unit', sa.String(length=16), nullable=False),
        sa.Column('achieved_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('source_log_id', postgresql.UUID(as_uuid=False), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['activity_type'], ['activity_taxonomy.activity_type'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_log_id'], ['activity_logs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_personal_bests_user_activity', 'personal_bests', ['user_id', 'activity_type'],
    )


def downgrade() -> None:
    op.drop_index('ix_personal_bests_user_activity', table_name='personal_bests')
    op.drop_table('personal_bests')
    op.drop_constraint('log_extraordinary_implies_implausible', 'activity_logs', type_='check')
    op.drop_column('activity_logs', 'extraordinary')
