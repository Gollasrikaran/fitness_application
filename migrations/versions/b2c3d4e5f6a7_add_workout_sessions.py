"""add workout_sessions table and activity_logs.workout_session_id

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'workout_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('planned_activity_count', sa.Integer(), nullable=False),
        sa.Column('completed_activity_count', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("status IN ('active','completed','abandoned')", name='ws_status_known'),
        sa.CheckConstraint('planned_activity_count >= 0', name='ws_planned_nonneg'),
        sa.CheckConstraint('completed_activity_count >= 0', name='ws_completed_nonneg'),
    )
    op.create_index(
        'ix_workout_sessions_user_started', 'workout_sessions', ['user_id', 'started_at'])
    op.create_index(
        'ix_workout_sessions_one_active', 'workout_sessions', ['user_id'],
        unique=True, postgresql_where=sa.text("status = 'active'"))

    op.add_column('activity_logs', sa.Column(
        'workout_session_id', postgresql.UUID(as_uuid=False), nullable=True))
    op.create_foreign_key(
        'fk_activity_logs_workout_session', 'activity_logs', 'workout_sessions',
        ['workout_session_id'], ['id'], ondelete='SET NULL')
    op.create_index(
        'ix_activity_logs_workout_session', 'activity_logs', ['workout_session_id'])


def downgrade() -> None:
    op.drop_index('ix_activity_logs_workout_session', table_name='activity_logs')
    op.drop_constraint('fk_activity_logs_workout_session', 'activity_logs', type_='foreignkey')
    op.drop_column('activity_logs', 'workout_session_id')

    op.drop_index('ix_workout_sessions_one_active', table_name='workout_sessions')
    op.drop_index('ix_workout_sessions_user_started', table_name='workout_sessions')
    op.drop_table('workout_sessions')
