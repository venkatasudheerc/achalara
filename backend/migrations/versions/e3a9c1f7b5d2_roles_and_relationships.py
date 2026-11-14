"""Roles: admin, advisor and client; spouses and guardians; private accounts

The old ``advisor`` login was the platform's super user, so it becomes ``admin``.
An advisor now manages the clients assigned to them (``clients.advisor_id``).
Clients name their spouse (``spouse_id``, kept in pairs) and a minor names their
guardian (``guardian_id``); who sees which accounts follows from these. An owner
may keep an account private from their spouse. A minor may have no email.

Revision ID: e3a9c1f7b5d2
Revises: d1e5c3a8b2f6
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = "e3a9c1f7b5d2"
down_revision = "d1e5c3a8b2f6"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("user_role", "users", type_="check")
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'advisor'")
    op.create_check_constraint("user_role", "users", "role IN ('admin', 'advisor', 'client')")

    op.add_column("clients", sa.Column("advisor_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_clients_advisor", "clients", "users", ["advisor_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_clients_advisor_id", "clients", ["advisor_id"])
    op.add_column("clients", sa.Column("spouse_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_clients_spouse", "clients", "clients", ["spouse_id"], ["id"], ondelete="SET NULL"
    )
    op.add_column("clients", sa.Column("guardian_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_clients_guardian", "clients", "clients", ["guardian_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_clients_guardian_id", "clients", ["guardian_id"])
    op.alter_column("clients", "email", existing_type=sa.String(255), nullable=True)

    op.add_column(
        "accounts",
        sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("accounts", "is_private")
    op.alter_column("clients", "email", existing_type=sa.String(255), nullable=False)
    op.drop_index("ix_clients_guardian_id", "clients")
    op.drop_constraint("fk_clients_guardian", "clients", type_="foreignkey")
    op.drop_column("clients", "guardian_id")
    op.drop_constraint("fk_clients_spouse", "clients", type_="foreignkey")
    op.drop_column("clients", "spouse_id")
    op.drop_index("ix_clients_advisor_id", "clients")
    op.drop_constraint("fk_clients_advisor", "clients", type_="foreignkey")
    op.drop_column("clients", "advisor_id")
    op.drop_constraint("user_role", "users", type_="check")
    op.execute("UPDATE users SET role = 'advisor' WHERE role = 'admin'")
    op.create_check_constraint("user_role", "users", "role IN ('advisor', 'client')")
