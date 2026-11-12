"""A client's own named groups of accounts ("My groups" on the landing page)."""
from typing import Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.account_group import AccountGroup, AccountGroupMember
from app.services.auth_service import AuthService
from app.services.portal_service import PortalError

MAX_GROUPS = 50


class AccountGroupService:
    """Groups belong to one client and may hold only accounts that client can see."""

    def __init__(self, db: Session, client_id: str):
        self.db = db
        self.client_id = client_id
        self._visible = {
            a.id for a, _ in AuthService(db).accounts_for_client(client_id)
        }

    def _out(self, group: AccountGroup) -> Dict:
        return {
            "id": group.id,
            "name": group.name,
            "position": group.position,
            # An account the client can no longer see drops out of the group.
            "account_ids": [
                m.account_id for m in group.members if m.account_id in self._visible
            ],
        }

    def _group(self, group_id: str) -> AccountGroup:
        group = (
            self.db.query(AccountGroup)
            .filter(
                AccountGroup.id == group_id, AccountGroup.client_id == self.client_id
            )
            .first()
        )
        if group is None:
            raise PortalError(404, "Group not found")
        return group

    def _clean_name(self, name: str, keep: Optional[str] = None) -> str:
        name = " ".join((name or "").split())
        if not name:
            raise PortalError(422, "Give the group a name")
        taken = (
            self.db.query(AccountGroup)
            .filter(
                AccountGroup.client_id == self.client_id,
                AccountGroup.id != (keep or ""),
            )
            .all()
        )
        if any(g.name.lower() == name.lower() for g in taken):
            raise PortalError(409, "A group with that name already exists")
        return name

    def _set_members(self, group: AccountGroup, account_ids: Sequence[str]) -> None:
        wanted = list(dict.fromkeys(account_ids))
        if any(a not in self._visible for a in wanted):
            raise PortalError(404, "Account not found")
        kept = [m for m in group.members if m.account_id in wanted]
        have = {m.account_id for m in kept}
        group.members = kept + [
            AccountGroupMember(account_id=a) for a in wanted if a not in have
        ]

    def list(self) -> List[Dict]:
        groups = (
            self.db.query(AccountGroup)
            .filter(AccountGroup.client_id == self.client_id)
            .order_by(AccountGroup.position, AccountGroup.name)
            .all()
        )
        return [self._out(g) for g in groups]

    def create(self, name: str, account_ids: Sequence[str] = ()) -> Dict:
        count = (
            self.db.query(AccountGroup)
            .filter(AccountGroup.client_id == self.client_id)
            .count()
        )
        if count >= MAX_GROUPS:
            raise PortalError(422, f"At most {MAX_GROUPS} groups")
        group = AccountGroup(
            client_id=self.client_id, name=self._clean_name(name), position=count
        )
        self._set_members(group, account_ids)
        self.db.add(group)
        self.db.commit()
        return self._out(group)

    def update(
        self, group_id: str, name: Optional[str], position: Optional[int]
    ) -> Dict:
        group = self._group(group_id)
        if name is not None:
            group.name = self._clean_name(name, keep=group.id)
        if position is not None:
            group.position = max(0, position)
        self.db.commit()
        return self._out(group)

    def set_accounts(self, group_id: str, account_ids: Sequence[str]) -> Dict:
        group = self._group(group_id)
        self._set_members(group, account_ids)
        self.db.commit()
        return self._out(group)

    def delete(self, group_id: str) -> None:
        self.db.delete(self._group(group_id))
        self.db.commit()
