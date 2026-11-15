"""Who owns an account and who sees it (Step 4).

An account has one or more owners (``account_owners``). Nobody else sees it
until an owner shares it (``account_access``, now with a level and a grantee that
may be an advisor's login). ``accounts.is_private`` goes: private is simply
"shared with nobody". A minor does not own: a custodial account is owned by its
custodian and held for the minor (``beneficiary_id``).

Today's visibility is kept by turning it into explicit view-only shares, so
nobody gains or loses sight of anything on the day: a spouse's non-private
accounts become shares to the other spouse; a minor's accounts become the
guardian's (held for the minor), shared with the guardian's spouse and the minor.
Each owner whose accounts were shared is told once (``clients.sharing_notice``).

Revision ID: b7d2e9a4c1f3
Revises: a3f8c1e6d2b9
Create Date: 2026-11-15
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "b7d2e9a4c1f3"
down_revision = "a3f8c1e6d2b9"
branch_labels = None
depends_on = None


def _id() -> str:
    return str(uuid.uuid4())


def upgrade() -> None:
    op.create_table(
        "account_owners",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(36), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "client_id", name="uq_account_owner"),
    )
    op.create_index("ix_account_owners_account_id", "account_owners", ["account_id"])
    op.create_index("ix_account_owners_client_id", "account_owners", ["client_id"])

    op.create_table(
        "person_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.String(36), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("client_id", "person_id", name="uq_person_link"),
    )
    op.create_index("ix_person_links_client_id", "person_links", ["client_id"])

    op.add_column("clients", sa.Column("sharing_notice", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("accounts", sa.Column("beneficiary_id", sa.String(36), sa.ForeignKey("clients.id", ondelete="SET NULL")))
    op.add_column("accounts", sa.Column("linked_by_id", sa.String(36), sa.ForeignKey("clients.id", ondelete="SET NULL")))
    op.create_index("ix_accounts_beneficiary_id", "accounts", ["beneficiary_id"])

    op.alter_column("account_access", "client_id", existing_type=sa.String(36), nullable=True)
    op.add_column("account_access", sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")))
    op.add_column("account_access", sa.Column("level", sa.String(10), nullable=False, server_default="view"))
    op.add_column("account_access", sa.Column("hidden", sa.Boolean(), nullable=False, server_default="false"))
    op.create_index("ix_account_access_user_id", "account_access", ["user_id"])
    op.create_unique_constraint("uq_account_access_user", "account_access", ["user_id", "account_id"])
    op.create_check_constraint("account_access_one_grantee", "account_access", "(client_id IS NULL) != (user_id IS NULL)")
    op.create_check_constraint("account_access_level", "account_access", "level IN ('view')")

    bind = op.get_bind()
    q = lambda sql, **p: bind.execute(sa.text(sql), p)  # noqa: E731

    # Every account's owner, and who linked it.
    for (account_id, client_id) in q("SELECT id, client_id FROM accounts").fetchall():
        q("INSERT INTO account_owners (id, account_id, client_id) VALUES (:i, :a, :c)",
          i=_id(), a=account_id, c=client_id)
    q("UPDATE accounts SET linked_by_id = client_id")

    # Relations already known.
    for (cid, spouse) in q("SELECT id, spouse_id FROM clients WHERE spouse_id IS NOT NULL").fetchall():
        q("INSERT INTO person_links (id, client_id, person_id, relation) VALUES (:i, :c, :p, 'spouse')",
          i=_id(), c=cid, p=spouse)
    for (minor, guardian, g_spouse) in q(
        "SELECT m.id, m.guardian_id, g.spouse_id FROM clients m JOIN clients g ON g.id = m.guardian_id"
    ).fetchall():
        for adult in {guardian, g_spouse} - {None}:
            q("INSERT INTO person_links (id, client_id, person_id, relation) VALUES (:i, :c, :p, 'minor')",
              i=_id(), c=adult, p=minor)

    told = set()

    def share(account_id: str, client_id: str, owner_id: str) -> None:
        if q("SELECT 1 FROM account_owners WHERE account_id=:a AND client_id=:c", a=account_id, c=client_id).first():
            return
        if q("SELECT 1 FROM account_access WHERE account_id=:a AND client_id=:c", a=account_id, c=client_id).first():
            return
        q("INSERT INTO account_access (id, account_id, client_id, level) VALUES (:i, :a, :c, 'view')",
          i=_id(), a=account_id, c=client_id)
        told.add(owner_id)

    # A spouse saw the other's accounts unless private.
    for (acct, owner, spouse) in q(
        "SELECT a.id, a.client_id, c.spouse_id FROM accounts a JOIN clients c ON c.id = a.client_id "
        "WHERE c.spouse_id IS NOT NULL AND a.is_private = false AND c.guardian_id IS NULL"
    ).fetchall():
        share(acct, spouse, owner)

    # A minor's accounts become the guardian's, held for the minor.
    for (acct, minor, guardian, g_spouse) in q(
        "SELECT a.id, a.client_id, m.guardian_id, g.spouse_id FROM accounts a "
        "JOIN clients m ON m.id = a.client_id JOIN clients g ON g.id = m.guardian_id"
    ).fetchall():
        q("UPDATE accounts SET client_id=:g, beneficiary_id=:m WHERE id=:a", g=guardian, m=minor, a=acct)
        q("UPDATE account_owners SET client_id=:g WHERE account_id=:a AND client_id=:m", g=guardian, a=acct, m=minor)
        if g_spouse:
            share(acct, g_spouse, guardian)
        share(acct, minor, guardian)

    for owner in told:
        q("UPDATE clients SET sharing_notice = true WHERE id=:c", c=owner)

    op.drop_column("accounts", "is_private")


def downgrade() -> None:
    op.add_column("accounts", sa.Column("is_private", sa.Boolean(), nullable=False, server_default="false"))
    op.drop_constraint("account_access_level", "account_access", type_="check")
    op.drop_constraint("account_access_one_grantee", "account_access", type_="check")
    op.drop_constraint("uq_account_access_user", "account_access", type_="unique")
    op.drop_index("ix_account_access_user_id", table_name="account_access")
    op.execute("DELETE FROM account_access WHERE client_id IS NULL")
    op.drop_column("account_access", "hidden")
    op.drop_column("account_access", "level")
    op.drop_column("account_access", "user_id")
    op.alter_column("account_access", "client_id", existing_type=sa.String(36), nullable=False)
    op.drop_index("ix_accounts_beneficiary_id", table_name="accounts")
    op.drop_column("accounts", "linked_by_id")
    op.drop_column("accounts", "beneficiary_id")
    op.drop_column("clients", "sharing_notice")
    op.drop_table("person_links")
    op.drop_table("account_owners")
