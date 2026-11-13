"""What the stages of the forecast hand each other."""
from dataclasses import dataclass, field


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
