"""add perf schema with daily valuation, holdings, prices and corporate actions

Revision ID: f6c864b1d2a8
Revises: beb22348332e
Create Date: 2026-10-11 10:45:47.236287

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f6c864b1d2a8'
down_revision = 'beb22348332e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Performance tables live in their own schema, apart from public.
    op.execute("CREATE SCHEMA IF NOT EXISTS perf")
    op.create_table('corporate_action',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('symbol', sa.String(length=50), nullable=False),
    sa.Column('effective_date', sa.Date(), nullable=False),
    sa.Column('action_type', sa.String(length=20), nullable=False),
    sa.Column('ratio', sa.Numeric(precision=12, scale=6), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('symbol', 'effective_date', 'action_type', name='uq_corporate_action_symbol_date_type'),
    schema='perf'
    )
    op.create_index(op.f('ix_perf_corporate_action_symbol'), 'corporate_action', ['symbol'], unique=False, schema='perf')
    op.create_table('daily_price',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('symbol', sa.String(length=50), nullable=False),
    sa.Column('price_date', sa.Date(), nullable=False),
    sa.Column('close', sa.Numeric(precision=15, scale=6), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('symbol', 'price_date', 'source', name='uq_daily_price_symbol_date_source'),
    schema='perf'
    )
    op.create_index(op.f('ix_perf_daily_price_symbol'), 'daily_price', ['symbol'], unique=False, schema='perf')
    op.create_table('daily_holding',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('account_id', sa.String(length=36), nullable=False),
    sa.Column('sleeve_id', sa.String(length=36), nullable=True),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('symbol', sa.String(length=50), nullable=False),
    sa.Column('security_type', sa.String(length=20), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=18, scale=8), nullable=False),
    sa.Column('price', sa.Numeric(precision=15, scale=6), nullable=True),
    sa.Column('market_value', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sleeve_id'], ['sleeves.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('account_id', 'as_of_date', 'symbol', name='uq_daily_holding_account_day'),
    schema='perf'
    )
    op.create_table('daily_valuation',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('sleeve_id', sa.String(length=36), nullable=True),
    sa.Column('account_id', sa.String(length=36), nullable=True),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('securities_value', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('cash_value', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('total_value', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('flow_in', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('flow_out', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('advisory_fees', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('return_factor', sa.Numeric(precision=18, scale=10), nullable=True),
    sa.Column('unpriced_value', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('basis', sa.String(length=15), nullable=False),
    sa.Column('is_provisional', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('(sleeve_id IS NULL) <> (account_id IS NULL)', name='daily_valuation_one_owner'),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sleeve_id'], ['sleeves.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('account_id', 'as_of_date', name='uq_daily_valuation_account'),
    sa.UniqueConstraint('sleeve_id', 'as_of_date', name='uq_daily_valuation_sleeve'),
    schema='perf'
    )
    op.drop_table('weekly_portfolio_snapshots')
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('weekly_portfolio_snapshots',
    sa.Column('id', sa.VARCHAR(length=36), autoincrement=False, nullable=False),
    sa.Column('sleeve_id', sa.VARCHAR(length=36), autoincrement=False, nullable=False),
    sa.Column('week_start_date', sa.DATE(), autoincrement=False, nullable=False),
    sa.Column('twr_period', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('twr_cumul', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('mwr_cumul', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('cost_basis', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('market_value', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('cash_in', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('cash_out', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('realized_gain', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['sleeve_id'], ['sleeves.id'], name='weekly_portfolio_snapshots_sleeve_id_fkey', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='weekly_portfolio_snapshots_pkey'),
    sa.UniqueConstraint('sleeve_id', 'week_start_date', name='uq_snapshot_sleeve_week')
    )
    op.drop_table('daily_valuation', schema='perf')
    op.drop_table('daily_holding', schema='perf')
    op.drop_index(op.f('ix_perf_daily_price_symbol'), table_name='daily_price', schema='perf')
    op.drop_table('daily_price', schema='perf')
    op.drop_index(op.f('ix_perf_corporate_action_symbol'), table_name='corporate_action', schema='perf')
    op.drop_table('corporate_action', schema='perf')
    op.execute("DROP SCHEMA IF EXISTS perf")
