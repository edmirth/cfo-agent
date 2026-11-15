"""The ledger held against the registers: receivables on 1500-1509 against
the open invoices, payables on 2400-2409 against the open bills."""
from datetime import date


from .ledger import _closing_or_none
from .models import FlowKind, Sources
import bankgap
import brreg
from . import texts


def _ar_residual(src: Sources, warnings: list[str]) -> tuple[float, bool]:
    """Receivables on 1500-1509 that the open invoices do not explain, and
    whether they are counted on. Returns (residual, counted).

    Read with the same carry-forward the rest of the module uses: a blank
    cell means unchanged, not zero. The range, not 1500 alone: receivables
    posted to 1501 and up belong to the same reconciliation, and
    `commitments` already treats them as one.

    The residual used to be counted as money in, in the committed line, over
    the next three weeks — money nobody could explain, propping up the floor
    the colour rests on. What it usually is: invoices older than the lookback,
    postings made straight to 1500, payments not matched to their invoices.
    Only a list cut off, or a register that could not be read whole, gives a
    reason to think it is ordinary invoicing on its way in; then it is
    expected, slowly. Otherwise it is in neither line, and named."""
    gl_ar = _closing_or_none(src.rows, 1500, 1509)
    ar_total = sum(i["amount"] for i in src.ar_open)
    if gl_ar is None or gl_ar - ar_total <= 1000:
        return 0.0, False
    residual = gl_ar - ar_total
    counted = bool(src.issued.get("truncated")) or not src.ar_complete
    warnings.append(
        texts.ar_residual(gl_ar, ar_total, residual, counted))
    return residual, counted


def _ap_residual(src: Sources, today: date, flows: list, warnings: list[str]) -> None:
    """The same check on 2400-2409 against the open bills.

    Being short on receivables flatters the forecast; being short on payables
    hides money going out. A liability is a credit balance, so what is owed is
    the balance negated."""
    gl_ap_raw = _closing_or_none(src.rows, 2400, 2409)
    if gl_ap_raw is None:
        return
    gl_ap = -gl_ap_raw
    ap_total = sum(b["amount"] for b in src.ap_open)
    if gl_ap - ap_total > 1000:
        residual = gl_ap - ap_total
        # Dated to this week, not spread like the receivables. An undated bill
        # is already late more often than it is early, and the overdue book
        # must not be made to look further away than it is.
        flows.append({"date": today, "amount": -residual,
                          "kind": FlowKind.AP_UNMATCHED,
                          "label": texts.ap_unmatched_label()})
        warnings.append(
            texts.ap_residual_short(gl_ap, ap_total, residual))
    elif ap_total - gl_ap > 1000:
        # The other direction, and it is not symmetrical. The register claims
        # more is outstanding than the ledger says is owed. It is NOT trimmed
        # to the ledger: the invoices carry real due dates and the difference
        # has no one invoice to take it from, so capping would mean choosing
        # which supplier to stop paying. Said out loud instead, and left
        # standing — paying too early is the survivable mistake of the two.
        warnings.append(
            texts.ap_residual_over(ap_total, gl_ap))


def _opening(com: dict, warnings: list[str]):
    """The balance the weeks open on. Returns (gap, booked, opening).

    Open on the money in the bank, not on the booked balance. The bank feed
    runs days ahead of the bookkeeping, and every week of the forecast, the
    low point with it, was shifted down by whatever had landed unposted.
    Measured in commitments, so the forecast and "how much of this is mine"
    open on the same figure."""
    gap = com.get("bank_gap")
    booked = com.get("bank_booked", com["bank"])
    opening = com["bank"]
    if gap is None:
        warnings.append(
            texts.bank_gap_unread())
        return gap, booked, opening
    warnings += gap["unknown"]
    # The figure is right as of the last imported line, so that date is
    # said whenever the feed is behind the last working day.
    if gap.get("stale"):
        warnings.append(
            texts.bank_feed_stale(gap["latest"]))
    if gap["approximate"]:
        warnings.append(
            texts.bank_gap_approximate())
    return gap, booked, opening


def _settle(src: Sources, gap: dict | None):
    """The open lists less what the bank has paid and the books have not, and
    less the customers in trouble with the register.
    Returns (ar_due, ar_paid, ap_due, ap_paid, risky, ar_at_risk).

    A payment the bank has and the ledger has not is still an open invoice
    in the register. With the opening lifted by that payment, scheduling the
    invoice as well collects the same krone twice — so what the unbooked
    lines have paid comes off the lists the schedules are built from. The
    full lists stay for the reconciliations against 1500 and 2400, which
    compare the register with the ledger and must see what the ledger sees,
    and for this month's invoicing, which is invoicing whether or not it has
    been paid. Only what the books do not have: a line booked but not matched
    in the reconciliation has closed its invoice already (`bankgap.unbooked`).
    """
    unbooked = (bankgap.unbooked(gap["unbooked"], gap.get("booked_unmatched") or [])
                if gap else [])
    ar_due, ar_paid = bankgap.settle(src.ar_open, unbooked, +1)
    ap_due, ap_paid = bankgap.settle(src.ap_open, unbooked, -1)
    # Customers Enhetsregisteret has in trouble, as of the last morning check.
    # A bankrupt customer's invoices are not money coming in: they leave the
    # schedule and are carried beside it, for the card that says so. One under
    # voluntary liquidation usually pays, and stays. Said on the customer's
    # card, not among the warnings: those are what the regnskapsfører has to
    # fix, and this is nothing in the books.
    risky = brreg.at_risk()
    ar_at_risk = [{**i, "register": risky[i["name"]]} for i in ar_due if i["name"] in risky]
    ar_due = [i for i in ar_due if not risky.get(i["name"], {}).get("excluded")]
    return ar_due, ar_paid, ap_due, ap_paid, risky, ar_at_risk
