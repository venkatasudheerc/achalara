"""The Dashboard's "Next best action" and "Insights"."""
from typing import List, Optional

from pydantic import BaseModel


class InsightChip(BaseModel):
    tone: str  # link | record | card | cash | investments | all
    label: str


class InsightAction(BaseModel):
    """What the one button does; the screen decides how (a link, a dialog)."""

    kind: str  # view | repair_login | update_from_file
    label: str
    view: Optional[str] = None  # accounts | connections ...
    sel: Optional[str] = None  # a selection, as in the address (account:<id>, kind:cash)
    login_id: Optional[str] = None
    account_id: Optional[str] = None


class InsightPart(BaseModel):
    label: str
    value: float


class InsightRow(BaseModel):
    label: str
    value: str


class InsightSpan(BaseModel):
    """One stretch of a record: a square per year, oldest first (True: it rose)."""

    when: str
    said: str
    years: List[bool]
    nums: str


class InsightVisual(BaseModel):
    """One of a closed set the screen can draw; only its own fields are set.

    meter: part, whole, left, right, warn. split: parts. countdown: days, note, rows.
    figure: text. record: spans.
    """

    type: str  # meter | split | countdown | figure | record
    part: Optional[float] = None
    whole: Optional[float] = None
    left: Optional[str] = None
    right: Optional[str] = None
    warn: Optional[bool] = None
    parts: Optional[List[InsightPart]] = None
    days: Optional[int] = None
    note: Optional[str] = None
    rows: Optional[List[InsightRow]] = None
    text: Optional[str] = None
    spans: Optional[List[InsightSpan]] = None


class InsightFinding(BaseModel):
    key: str  # stable: the rule and what it is about
    rule: str
    tier: str  # nudge | insight
    rank: int  # lower is more pressing
    chip: InsightChip
    title: str
    detail: str
    must: bool  # stays in place until it is done; never rolls
    when: Optional[str] = None
    foot: Optional[str] = None
    visual: Optional[InsightVisual] = None
    action: Optional[InsightAction] = None
    wide: bool
    account_ids: List[str]
    link: Optional[InsightAction] = None


class InsightsResponse(BaseModel):
    nudges: List[InsightFinding]
    insights: List[InsightFinding]
