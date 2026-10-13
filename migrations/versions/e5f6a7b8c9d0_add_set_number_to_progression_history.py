"""add set_number to progression_history, extend reason enum

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-07 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_REASONS = "reason IN ('curve','hold','reduce','floor','escalation','double_progression')"
NEW_REASONS = (
    "reason IN ('curve','hold','reduce','floor','escalation','double_progression',"
    "'set_created','set_boost','pro_level')"
)


def upgrade() -> None:
    op.add_column('progression_history', sa.Column('set_number', sa.Integer(), nullable=True))
    op.drop_constraint('ph_reason_known', 'progression_history', type_='check')
    op.create_check_constraint('ph_reason_known', 'progression_history', NEW_REASONS)


def downgrade() -> None:
    op.drop_constraint('ph_reason_known', 'progression_history', type_='check')
    op.create_check_constraint('ph_reason_known', 'progression_history', OLD_REASONS)
    op.drop_column('progression_history', 'set_number')
