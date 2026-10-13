"""add condition_interactions table (combined-conditions safety check)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'condition_interactions',
        sa.Column('condition_a', sa.String(length=64), nullable=False),
        sa.Column('condition_b', sa.String(length=64), nullable=False),
        sa.Column('activity_type', sa.String(length=64), nullable=False),
        sa.Column('verdict', sa.String(length=16), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('reviewer', sa.String(length=128), nullable=False),
        sa.Column('reviewed_at', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['condition_a'], ['conditions.condition_code'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['condition_b'], ['conditions.condition_code'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['activity_type'], ['activity_taxonomy.activity_type'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('condition_a', 'condition_b', 'activity_type'),
        sa.CheckConstraint("verdict IN ('modify','avoid')", name='ci_verdict_known'),
        sa.CheckConstraint("condition_a < condition_b", name='ci_pair_canonical_order'),
    )
    op.create_index('ix_condition_interactions_a', 'condition_interactions', ['condition_a'])
    op.create_index('ix_condition_interactions_b', 'condition_interactions', ['condition_b'])

    # NULL for an ordinary single-condition override (unchanged meaning); set
    # only when the override was triggered by a condition PAIR, so the
    # consent record names both conditions that were actually shown to the
    # user, not just one.
    op.add_column('override_consents', sa.Column('condition_code_2', sa.String(length=64), nullable=True))
    op.create_foreign_key(
        'fk_override_consents_condition_code_2', 'override_consents',
        'conditions', ['condition_code_2'], ['condition_code'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_override_consents_condition_code_2', 'override_consents', type_='foreignkey')
    op.drop_column('override_consents', 'condition_code_2')
    op.drop_index('ix_condition_interactions_b', table_name='condition_interactions')
    op.drop_index('ix_condition_interactions_a', table_name='condition_interactions')
    op.drop_table('condition_interactions')
