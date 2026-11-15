"""Who owns an account and who else sees it: owners, shares, hand-over, People.

Rules (Step 4):
- An account has one or more owners; any owner may share it or change its owners.
  The client who linked it controls it until one of its owners has a sign-in.
- Nobody else sees it until an owner shares it, person by person (view only).
  An owner's advisor is shared with like anyone else (a login, not a client).
- A new owner needs no acceptance. A minor does not own: a custodial account is
  owned by its custodian and held for the minor (``beneficiary_id``); handing it
  over needs the minor to have a sign-in.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.account import Account, AccountOwner
from app.models.client import FAMILY_RELATIONS, Client, PersonLink
from app.models.user import LEVEL_VIEW, ROLE_ADVISOR, AccountAccess, User
from app.services.auth_service import AuthError, AuthService, display_name


class SharingService:
    def __init__(self, db: Session, client_id: str):
        self.db = db
        self.client_id = client_id
        self.auth = AuthService(db)

    # -- helpers -------------------------------------------------------

    def _account(self, account_id: str, control: bool = True) -> Account:
        """The account, if the viewer sees it (and, with ``control``, may change
        its sharing). Anything else is the same 404."""
        account = self.db.get(Account, account_id)
        if account is None:
            raise AuthError(404, "Account not found")
        if control:
            if not self.auth.can_control(self.client_id, account):
                raise AuthError(404, "Account not found")
        elif account_id not in {a.id for a, _ in self.auth.accounts_for_client(self.client_id)}:
            raise AuthError(404, "Account not found")
        return account

    def _person(self, person_id: str) -> Client:
        person = self.db.get(Client, person_id)
        known = {c.id for c, _ in self.auth.relatives(self.client_id)}
        shared = {
            row[0]
            for row in self.db.query(AccountAccess.client_id)
            .join(Account, Account.id == AccountAccess.account_id)
            .join(AccountOwner, AccountOwner.account_id == Account.id)
            .filter(AccountOwner.client_id == self.client_id, AccountAccess.client_id.isnot(None))
        }
        if person is None or person.id == self.client_id or person.id not in known | shared:
            raise AuthError(404, "Person not found")
        return person

    def _advisor(self) -> Optional[User]:
        me = self.db.get(Client, self.client_id)
        return self.db.get(User, me.advisor_id) if me and me.advisor_id else None

    # -- one account ---------------------------------------------------

    def sharing(self, account_id: str) -> Dict:
        account = self._account(account_id, control=False)
        owners = self.auth.owner_ids(account)
        shares: List[Dict] = []
        for access in self.db.query(AccountAccess).filter(AccountAccess.account_id == account.id):
            if access.client_id:
                who = self.db.get(Client, access.client_id)
                shares.append({"kind": "person", "id": who.id, "name": who.name, "level": access.level})
            else:
                who = self.db.get(User, access.user_id)
                shares.append({"kind": "advisor", "id": who.id, "name": who.name, "level": access.level})
        beneficiary = self.db.get(Client, account.beneficiary_id) if account.beneficiary_id else None
        return {
            "account_id": account.id,
            "name": display_name(account),
            "can_manage": self.auth.can_control(self.client_id, account),
            "owners": [
                {"id": o.id, "name": o.name, "has_login": self.auth.has_login(o.id)}
                for o in self.db.query(Client).filter(Client.id.in_(owners)).order_by(Client.name)
            ],
            "held_for": {"id": beneficiary.id, "name": beneficiary.name} if beneficiary else None,
            "shared_with": sorted(shares, key=lambda s: s["name"]),
            "advisor": ({"id": a.id, "name": a.name} if (a := self._advisor()) else None),
        }

    def share(self, account_id: str, person_id: Optional[str] = None, advisor: bool = False) -> Dict:
        account = self._account(account_id)
        if advisor:
            who = self._advisor()
            if who is None or who.role != ROLE_ADVISOR:
                raise AuthError(422, "You have no advisor to share with.")
            exists = self.db.query(AccountAccess).filter(
                AccountAccess.account_id == account.id, AccountAccess.user_id == who.id
            ).first()
            if not exists:
                self.db.add(AccountAccess(account_id=account.id, user_id=who.id, level=LEVEL_VIEW))
        else:
            person = self._person(person_id or "")
            if person.id in self.auth.owner_ids(account):
                raise AuthError(422, "They already own this account.")
            exists = self.db.query(AccountAccess).filter(
                AccountAccess.account_id == account.id, AccountAccess.client_id == person.id
            ).first()
            if exists:
                exists.hidden = False
            else:
                self.db.add(AccountAccess(account_id=account.id, client_id=person.id, level=LEVEL_VIEW))
        self.db.commit()
        return self.sharing(account_id)

    def unshare(self, account_id: str, person_id: Optional[str] = None, advisor: bool = False) -> Dict:
        account = self._account(account_id)
        query = self.db.query(AccountAccess).filter(AccountAccess.account_id == account.id)
        if advisor:
            who = self._advisor()
            query = query.filter(AccountAccess.user_id == (who.id if who else None))
        else:
            query = query.filter(AccountAccess.client_id == person_id)
        if not query.delete():
            raise AuthError(404, "Not shared with them")
        self.db.commit()
        return self.sharing(account_id)

    def set_owners(self, account_id: str, owner_ids: List[str], keep_view: bool = True) -> Dict:
        """The account's owners are now exactly ``owner_ids`` (no acceptance
        needed). Anyone who stops owning keeps a view-only share when
        ``keep_view``; existing shares stay."""
        account = self._account(account_id)
        wanted = list(dict.fromkeys(owner_ids))
        if not wanted:
            raise AuthError(422, "An account needs an owner.")
        for owner_id in wanted:
            owner = self.db.get(Client, owner_id)
            if owner is None or (owner_id != self.client_id and owner_id not in {
                c.id for c, _ in self.auth.relatives(self.client_id)
            }):
                raise AuthError(404, "Person not found")
            if owner.is_minor:
                raise AuthError(422, "A minor does not own an account. Hold it for them instead.")
        before = set(self.auth.owner_ids(account))
        self.db.query(AccountOwner).filter(
            AccountOwner.account_id == account.id, AccountOwner.client_id.notin_(wanted)
        ).delete(synchronize_session=False)
        for owner_id in wanted:
            if owner_id not in before:
                self.db.add(AccountOwner(account_id=account.id, client_id=owner_id))
                # An owner needs no share of their own.
                self.db.query(AccountAccess).filter(
                    AccountAccess.account_id == account.id, AccountAccess.client_id == owner_id
                ).delete()
        account.client_id = wanted[0]
        if keep_view:
            for gone in before - set(wanted):
                self.db.add(AccountAccess(account_id=account.id, client_id=gone, level=LEVEL_VIEW))
        self.db.commit()
        # The one who changed it may no longer control it; answer for what they still see.
        try:
            return self.sharing(account_id)
        except AuthError:
            return {"account_id": account.id, "name": display_name(account), "can_manage": False,
                    "owners": [], "held_for": None, "shared_with": [], "advisor": None}

    def hold_for(self, account_id: str, minor_id: Optional[str]) -> Dict:
        """Hold the account for a minor (a custodial account), or stop."""
        account = self._account(account_id)
        if minor_id:
            minor = self.db.get(Client, minor_id)
            if minor is None or not minor.is_minor or minor.id not in {
                c.id for c, r in self.auth.relatives(self.client_id) if r == "minor"
            }:
                raise AuthError(404, "Person not found")
            account.beneficiary_id = minor.id
        else:
            account.beneficiary_id = None
        self.db.commit()
        return self.sharing(account_id)

    def hand_over(self, account_id: str, keep_view: bool = True) -> Dict:
        """Give a custodial account to the minor it is held for, who must have a sign-in."""
        account = self._account(account_id)
        if not account.beneficiary_id:
            raise AuthError(422, "This account is not held for anyone.")
        minor = self.db.get(Client, account.beneficiary_id)
        if not self.auth.has_login(minor.id):
            raise AuthError(409, f"{minor.name} needs a sign-in before the account can be handed over.")
        if minor.is_minor:
            self.auth.set_guardian(minor.id, None)
        account.beneficiary_id = None
        self.db.commit()
        return self.set_owners(account_id, [minor.id], keep_view=keep_view)

    def stop_seeing(self, account_id: str) -> None:
        """Hide an account shared with the viewer from their own screens."""
        access = self.db.query(AccountAccess).filter(
            AccountAccess.account_id == account_id, AccountAccess.client_id == self.client_id
        ).first()
        if access is None:
            raise AuthError(404, "Account not found")
        access.hidden = True
        self.db.commit()

    # -- People --------------------------------------------------------

    def people(self) -> Dict:
        """Everyone connected to the viewer by a relation or a share, grouped
        Family · Others · Your advisor, with what each shares in each direction."""
        mine = {a.id: a for a, shared in self.auth.accounts_for_client(self.client_id) if not shared}
        seen_by_me = {a.id: a for a, shared in self.auth.accounts_for_client(self.client_id) if shared}
        relation = {c.id: (c, r) for c, r in self.auth.relatives(self.client_id)}
        people: Dict[str, Dict] = {}

        def row(client: Client, rel: Optional[str]) -> Dict:
            return people.setdefault(client.id, {
                "id": client.id, "name": client.name, "relation": rel or "other",
                "has_login": self.auth.has_login(client.id), "is_minor": client.is_minor,
                "you_share": 0, "shares_with_you": 0, "own_together": 0, "you_hold_for": 0,
            })

        for client, rel in relation.values():
            row(client, rel)
        for account in mine.values():
            for access in self.db.query(AccountAccess).filter(
                AccountAccess.account_id == account.id, AccountAccess.client_id.isnot(None)
            ):
                person = self.db.get(Client, access.client_id)
                row(person, relation.get(person.id, (None, None))[1])["you_share"] += 1
            for owner_id in self.auth.owner_ids(account):
                if owner_id != self.client_id:
                    row(self.db.get(Client, owner_id), relation.get(owner_id, (None, None))[1])["own_together"] += 1
            if account.beneficiary_id:
                row(self.db.get(Client, account.beneficiary_id), "minor")["you_hold_for"] += 1
        for account in seen_by_me.values():
            if account.beneficiary_id == self.client_id:
                continue
            owner = self.db.get(Client, account.client_id)
            row(owner, relation.get(owner.id, (None, None))[1])["shares_with_you"] += 1

        out = list(people.values())
        for p in out:
            p["group"] = "family" if p["relation"] in FAMILY_RELATIONS else "others"
        advisor = self._advisor()
        advisor_row = None
        if advisor is not None:
            shared = {
                row[0] for row in self.db.query(AccountAccess.account_id).filter(AccountAccess.user_id == advisor.id)
            }
            advisor_row = {"id": advisor.id, "name": advisor.name,
                           "you_share": len(shared & set(mine)), "not_shared": len(set(mine) - shared)}
        me = self.db.get(Client, self.client_id)
        return {
            "people": sorted(out, key=lambda p: (p["group"], p["name"])),
            "advisor": advisor_row,
            "notice": bool(me and me.sharing_notice),
            "your_accounts": [
                {"id": a.id, "name": display_name(a), "owners": [
                    self.db.get(Client, i).name for i in self.auth.owner_ids(a)],
                 "seen_by": [s["name"] for s in self.sharing(a.id)["shared_with"]]}
                for a in mine.values()
            ],
            "shared_with_you": [
                {"id": a.id, "name": display_name(a), "owner": self.db.get(Client, a.client_id).name,
                 "level": LEVEL_VIEW}
                for a in seen_by_me.values() if a.beneficiary_id != self.client_id
            ],
        }

    def dismiss_notice(self) -> None:
        me = self.db.get(Client, self.client_id)
        if me:
            me.sharing_notice = False
            self.db.commit()
