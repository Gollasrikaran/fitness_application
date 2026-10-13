"""add usefulness_rank to safety_grid

Revision ID: a1b2c3d4e5f6
Revises: 920c2589bf03
Create Date: 2026-09-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '920c2589bf03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, no CheckConstraint: the invariant ("avoid" -> null, otherwise
    # required) is enforced by app.catalog.loader.load_safety_grid at load
    # time, same as overall grid coverage. A DB-level constraint would reject
    # this very migration, since it runs before the loader ever populates a
    # real value (Procfile: `alembic upgrade head && python -m app.catalog.loader`).
    op.add_column('safety_grid', sa.Column('usefulness_rank', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('safety_grid', 'usefulness_rank')
