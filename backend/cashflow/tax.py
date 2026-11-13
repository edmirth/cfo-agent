"""VAT and employer's contribution read off the ledger."""
from .common import AGA_ACCRUED, VAT_ACCRUED
from .ledger import _closing_range


# Below this the output-VAT balance is too small to read a ratio off, which
# happens for a few days after every settlement clears both accounts.
VAT_RATIO_MIN = 50_000


def _vat_input_share(rows: list) -> tuple[float, bool]:
    """How much of the output VAT the input VAT cancels, per this company.

    Not every krone collected is paid over: VAT on what the company buys is
    deducted first. The share is read from 2700 against 2710 rather than
    assumed, and those two are the one pair in the ledger that needs no
    differencing — a settlement clears both on the same day, so their ratio
    inside a term is the live ratio with no drift across the boundary.

    Returns the share and whether it could be measured. Unmeasured means the
    whole output VAT is scheduled out, which is the safe direction to be wrong.
    """
    out = abs(_closing_range(rows, 2700, 2709))
    inn = abs(_closing_range(rows, 2710, 2719))
    if out < VAT_RATIO_MIN:
        return 0.0, False
    # Capped: a deduction above half would mean the company buys nearly as much
    # as it sells, which for a cleaning company means a posting error, not a
    # bargain, and a too-large deduction understates the payment.
    return min(inn / out, 0.5), True
VAT_SETTLEMENT = (2740, 2749)
VAT_OUTPUT, VAT_INPUT = (2700, 2709), (2710, 2719)


def _settled(postings: list[dict]) -> tuple[float, float]:
    """(VAT, AGA): what this month's settlements and payments moved on the
    accrual accounts, a debit positive, to take off the month's movement.

    A VAT settlement is a voucher that reaches 2740, or one that clears output
    against input VAT itself: a debit on 2700-2709 with a credit on 2710-2719.
    An AGA payment is a voucher whose net on 2770-2779 is a debit; the payroll
    voucher credits it, and a reversal of one is netted inside its own voucher.
    """
    def acct(p):
        try:
            return int(str(p.get("accountNumber"))[:4])
        except (TypeError, ValueError):
            return None

    def within(n, rng):
        return n is not None and rng[0] <= n <= rng[1]

    vouchers: dict = {}
    for i, p in enumerate(postings):
        vouchers.setdefault(p.get("voucherId", ("loose", i)), []).append(
            (acct(p), float(p.get("amount") or 0)))
    vat = aga = 0.0
    for lines in vouchers.values():
        settles = (any(within(n, VAT_SETTLEMENT) for n, _ in lines)
                   or (any(within(n, VAT_OUTPUT) and a > 0 for n, a in lines)
                       and any(within(n, VAT_INPUT) and a < 0 for n, a in lines)))
        if settles:
            vat += sum(a for n, a in lines if within(n, VAT_ACCRUED))
        on_aga = sum(a for n, a in lines if within(n, AGA_ACCRUED))
        if on_aga > 0:
            aga += on_aga
    return vat, aga
