"""What the stages of the forecast hand each other."""
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import NotRequired, TypedDict


class Line(StrEnum):
    """The two lines the weeks are walked down."""
    COMMITTED = "committed"   # money already agreed: the floor
    EXPECTED = "expected"     # the floor plus continued trading


class FlowKind(StrEnum):
    """What a flow is. Each kind belongs to one line, so a stage adds its
    flows to one list and the line is never a decision made twice."""
    AR = "ar"                           # an open customer invoice
    AR_LATE = "ar_late"                 # overdue up to LATE_DAYS, spread over weeks
    AR_SLOW = "ar_slow"                 # overdue up to DOUBTFUL_DAYS, slowly
    AR_UNMATCHED = "ar_unmatched"       # 1500 beyond the open invoices, list cut off
    AP = "ap"                           # an open supplier bill
    AP_UNMATCHED = "ap_unmatched"       # 2400 beyond the open bills
    FIXED = "fixed"                     # rent, leasing, insurance still to be billed
    RECURRING = "recurring"             # a contract customer's lowest recent month
    RECURRING_USUAL = "recurring_usual"  # the rest of his usual month
    NEW_SALES = "new_sales"             # other invoicing not yet sent
    STATUTORY = "statutory"             # taxes and debts commitments dates
    WAGES = "wages"                     # a pay day
    AGA_FUTURE = "aga_future"           # employer's contribution on a run to come
    VAT_RECURRING = "vat_recurring"     # VAT on the contract invoicing
    VAT_FUTURE = "vat_future"           # VAT on the rest of the invoicing
    OPEX_RECURRING = "opex_recurring"   # running costs tied to the floor
    OPEX = "opex"                       # the rest of the running costs

    @property
    def line(self) -> Line:
        return Line.EXPECTED if self in _EXPECTED else Line.COMMITTED

    @property
    def counts_after(self) -> bool:
        """Kept when it lands after the window: customer invoices sent, and
        the invoicing sent inside the window. Not the slow and doubtful
        spreads, which are ours, nor the accounts' fallback, which has no
        invoice."""
        return self in _AFTER


_EXPECTED = {FlowKind.AR_SLOW, FlowKind.AR_UNMATCHED, FlowKind.RECURRING_USUAL,
             FlowKind.NEW_SALES, FlowKind.VAT_FUTURE, FlowKind.OPEX}
_AFTER = {FlowKind.AR, FlowKind.RECURRING, FlowKind.RECURRING_USUAL, FlowKind.NEW_SALES}


class Flow(TypedDict):
    """Money in (positive) or out (negative) on a day, on one line."""
    date: date
    amount: float
    kind: FlowKind
    label: str
    month: NotRequired[tuple[int, int]]    # the month invoiced or billed
    customer: NotRequired[str]


def split_lines(flows: list[Flow]) -> tuple[list[Flow], list[Flow]]:
    """(committed, expected), each in the order the flows were added."""
    committed = [f for f in flows if FlowKind(f["kind"]).line is Line.COMMITTED]
    expected = [f for f in flows if FlowKind(f["kind"]).line is Line.EXPECTED]
    return committed, expected


@dataclass
class Sources:
    """What the forecast read, before any of it is interpreted."""
    rows: list
    columns: list
    com: dict
    ar_open: list
    ar_complete: bool
    ap_open: list
    ap_complete: bool
    prior: object
    paid: object
    wages_paid: object
    tax_posts: list
    issued: dict
    supplier_history: list
    customer_history: list
    warnings: list[str] = field(default_factory=list)



@dataclass
class Runs:
    """The invoicing still to be sent, as read off the register."""
    by_month: dict
    found: list
    from_register: bool
    other_by_month: dict
    other_measured: dict | None



@dataclass
class Pay:
    per_day: float
    measured: dict | None
    months: list
