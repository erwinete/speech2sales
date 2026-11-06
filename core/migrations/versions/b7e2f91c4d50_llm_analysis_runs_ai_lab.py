"""llm_analysis_runs: история ИИ-разборов AI Lab (ТЗ v3.0 §3.2)

Revision ID: b7e2f91c4d50
Revises: 86a84127e12a
Create Date: 2026-11-07 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e2f91c4d50'
down_revision: Union[str, None] = '86a84127e12a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'llm_analysis_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('org_id', sa.Uuid(), nullable=False),
        sa.Column('author_id', sa.Uuid(), nullable=True),
        sa.Column('mode', sa.String(length=32), nullable=False),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('model_id', sa.String(length=128), nullable=False),
        sa.Column('filter_spec', sa.JSON(), nullable=False),
        sa.Column('pii_config', sa.JSON(), nullable=False),
        sa.Column('prompt_text', sa.Text(), nullable=False),
        sa.Column('calls_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('call_ids', sa.JSON(), nullable=True),
        sa.Column('result_markdown', sa.Text(), nullable=True),
        sa.Column('token_usage', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='done', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_llm_runs_org_created', 'llm_analysis_runs', ['org_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_llm_runs_org_created', table_name='llm_analysis_runs')
    op.drop_table('llm_analysis_runs')
