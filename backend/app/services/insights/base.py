"""The shape of a finding, and of the visuals a rule may ask for.

A rule returns ``Finding`` values. The screen knows only the closed set of
visuals below, so a new rule never needs a new component: it picks one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

NUDGE = "nudge"      # something to do: rolls through "Next best action"
INSIGHT = "insight"  # a fact about what is held: no action

# A chip names the subject at a glance (tone picks its colour on screen).
CHIPS = {
    "connection": ("link", "Connection"),
    "record": ("record", "Record"),
    "card": ("card", "Credit card"),
    "cash": ("cash", "Cash"),
    "investments": ("investments", "Investments"),
    "options": ("investments", "Options"),
    "taxable": ("investments", "Taxable"),
    "everything": ("all", "Everything"),
    "markets": ("all", "Markets"),
}


def chip(name: str) -> Dict[str, str]:
    tone, label = CHIPS[name]
    return {"tone": tone, "label": label}


def meter(part: float, whole: float, left: str, right: str, warn: bool = False) -> Dict:
    return {"type": "meter", "part": part, "whole": whole, "left": left, "right": right, "warn": warn}


def split(parts: List[Dict]) -> Dict:
    """``parts``: a label and a value each; the screen colours them in order."""
    return {"type": "split", "parts": parts}


def countdown(days: int, note: str, rows: Optional[List[Dict]] = None) -> Dict:
    return {"type": "countdown", "days": days, "note": note, "rows": rows or []}


def figure(text: str) -> Dict:
    return {"type": "figure", "text": text}


def record(spans: List[Dict]) -> Dict:
    return {"type": "record", "spans": spans}


def view(name: str, sel: Optional[str] = None, label: str = "") -> Dict:
    return {"kind": "view", "label": label, "view": name, "sel": sel}


def repair_login(login_id: str, label: str = "Sign in again") -> Dict:
    return {"kind": "repair_login", "label": label, "login_id": login_id}


def update_from_file(account_id: str) -> Dict:
    return {"kind": "update_from_file", "label": "Update from a file", "account_id": account_id}


@dataclass
class Finding:
    key: str                       # stable: rule and subject
    rule: str
    tier: str                      # NUDGE or INSIGHT
    rank: int                      # lower is more pressing
    chip: Dict[str, str]
    title: str
    detail: str
    must: bool = False             # stays in place until it is done; never rolls
    when: Optional[str] = None     # "since 11 Nov"
    foot: Optional[str] = None     # where the figure comes from and when
    visual: Optional[Dict] = None
    action: Optional[Dict] = None
    wide: bool = False
    account_ids: List[str] = field(default_factory=list)
    link: Optional[Dict] = None    # a quiet link beneath an insight


class Rule:
    """One thing worth noticing. ``find`` reads the context and returns findings.

    ``allow_incomplete``: set only by rules that are *about* an incomplete
    record or a stopped login; every other finding built on an account whose
    record is incomplete is dropped by the service.
    """

    id: str = ""
    allow_incomplete: bool = False

    def find(self, ctx: "Context") -> List[Finding]:  # noqa: F821
        raise NotImplementedError
