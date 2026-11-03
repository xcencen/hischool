"""Add pilot eligibility, versioned consent and immutable run bindings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

revision = '0007_assistant_access'
down_revision = '0006_assistant'
branch_labels = None
depends_on = None


def table(name, *columns):
    op.create_table(name,
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, comment='主键ID'),
        sa.Column('create_time', DATETIME(fsp=6), nullable=False, comment='创建时间（UTC）'),
        sa.Column('update_time', DATETIME(fsp=6), nullable=False, comment='更新时间（UTC）'),
        *columns, mysql_engine='InnoDB', mysql_charset='utf8mb4')


def upgrade():
    table('assistant_policies',
        sa.Column('version', sa.String(64, collation='utf8mb4_bin'), nullable=False),
        sa.Column('title', sa.String(100), nullable=False), sa.Column('text', sa.Text(), nullable=False),
        sa.Column('current', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.UniqueConstraint('version', name='uq_assistant_policies_version'))
    op.create_index('ix_assistant_policies_current', 'assistant_policies', ['current'])
    table('assistant_access',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('eligible', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('generation', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.UniqueConstraint('user_id', name='uq_assistant_access_user_id'),
        sa.CheckConstraint('generation >= 1', name='ck_assistant_access_generation'))
    table('assistant_consents',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('generation', sa.Integer(), nullable=False),
        sa.Column('policy_id', sa.Integer(), sa.ForeignKey('assistant_policies.id'), nullable=False),
        sa.UniqueConstraint('user_id', 'generation', 'policy_id', name='uq_assistant_consents_binding'))
    op.create_index('ix_assistant_consents_policy_id', 'assistant_consents', ['policy_id'])
    table('assistant_run_access',
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('assistant_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('generation', sa.Integer(), nullable=False),
        sa.Column('policy_id', sa.Integer(), sa.ForeignKey('assistant_policies.id'), nullable=False),
        sa.UniqueConstraint('run_id', name='uq_assistant_run_access_run_id'))
    op.create_index('ix_assistant_run_access_policy_id', 'assistant_run_access', ['policy_id'])


def downgrade():
    # Destructive rollback is deliberately unavailable even though all changes are additive.
    raise RuntimeError('Keep consent and accounting records; roll back application images with assistant disabled.')
