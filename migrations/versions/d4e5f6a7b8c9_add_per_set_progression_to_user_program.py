"""add per-set independent progression columns to user_program

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-07 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_program', sa.Column('reps_ceiling', sa.Numeric(6, 2), nullable=True))
    op.add_column('user_program', sa.Column(
        'set_targets', postgresql.ARRAY(sa.Numeric(10, 2)), nullable=True))
    op.add_column('user_program', sa.Column(
        'internal_set_targets', postgresql.ARRAY(sa.Numeric(12, 6)), nullable=True))
    op.add_column('user_program', sa.Column(
        'pro_leveled_at', sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        'prog_reps_ceiling_positive', 'user_program',
        'reps_ceiling IS NULL OR reps_ceiling > 0',
    )


def downgrade() -> None:
    op.drop_constraint('prog_reps_ceiling_positive', 'user_program', type_='check')
    op.drop_column('user_program', 'pro_leveled_at')
    op.drop_column('user_program', 'internal_set_targets')
    op.drop_column('user_program', 'set_targets')
    op.drop_column('user_program', 'reps_ceiling')
