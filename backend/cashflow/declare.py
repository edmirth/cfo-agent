"""What the forecast declares beside the weeks: where every figure came from,
for the owner, the cards and the clean-up list; and the forecast kept."""
import logging
from datetime import date

import bankgap
import brreg
import forecasts
import scoring

from .common import MONTH_NAMES, SEASON_WEIGHT
from .models import Pay, Runs, Sources
from . import texts

log = logging.getLogger("cfo.cashflow")

# The register and the accounts are compared on next month: further apart than
# this, the forecast says so rather than choosing between them.
REGISTER_CHECK = 0.35


def _declare_pay(data: dict, credit_source: str, pay: Pay) -> None:
    """Where the credit days and the pay per pay day came from."""
    a = data["assumptions"]
    a["credit_days_source"] = credit_source
    a["lonn_per_lonningsdag"] = {
        "belop": round(pay.per_day, 2),
        "kilde": "lønnsbilagene" if pay.measured else "lønnskontoene",
        "maneder": (pay.measured or {}).get("months", [])}


def _declare_costs(data: dict, rates: dict, opex_vat: float, booked_opex: float,
                   bank_costs: dict | None, fixed_found: list, profile: dict) -> None:
    """Where the running costs came from, and the fixed bills the committed
    line carries, for the owner to check against what he knows he pays."""
    a = data["assumptions"]
    # What the bills cost in cash, against the P&L figure beside it, and what
    # this month has already booked — netted off, as `fakturert_denne_maneden`.
    a["mva_paa_kostnader"] = round(opex_vat, 2)
    a["monthly_opex_cash"] = round(rates["opex"] + opex_vat, 2)
    a["kostnader_bokfort_denne_maneden"] = round(booked_opex, 2)
    a["kostnader_kilde"] = "banken" if bank_costs else "regnskapet"
    a["kostnader_fra_banken"] = bank_costs and {
        "nivaa_mnd": bank_costs["level"],
        "maneder": bank_costs["months"],
        "andeler": bank_costs["shares"],
        "sikker_andel": bank_costs["certain_share"],
        "betalt_denne_maneden": bank_costs["paid_this_month"]}
    data["fixed_costs"] = fixed_found
    a["faste_regninger_mnd"] = round(sum(
        f["amount"] / (1 if f["cadence"] == "månedlig" else 3) for f in fixed_found), 2)
    a["kostnadsprofil"] = profile


def _declare_sales(data: dict, runs: Runs, sales_profile: dict, sales_lag: int,
                   season: dict, months: dict, warnings: list[str]) -> None:
    """The contract customers the committed line counts on, how the rest of
    the invoicing was read, and the register held against the accounts."""
    a = data["assumptions"]
    # He knows which buildings are on a monthly contract better than we do.
    data["recurring_sales"] = runs.found
    a["fast_fakturering_mnd"] = round(sum(f["amount"] for f in runs.found), 2)
    a["fakturaprofil"] = {**sales_profile, "forsinkelse_dager": sales_lag}
    a["sesong"] = {
        k: ({MONTH_NAMES[m - 1]: v for m, v in sorted(idx.items())} if idx else None)
        for k, idx in season.items()}
    a["sesong_vekt"] = SEASON_WEIGHT
    a["omsetning_per_maned"] = months["sales"]
    a["fakturering_fra"] = "fakturaregisteret" if runs.from_register else "regnskapet"
    # The accounts as a check on the register, on next month: the whole of it
    # is still to be invoiced, so the two should tell the same story.
    invoicing = months["invoicing"]
    nxt = invoicing[1] if len(invoicing) > 1 else None
    if nxt and nxt["regnskapet"] > 0:
        invoiced = nxt["fast_vanlig"] + nxt["annen"]
        if abs(invoiced - nxt["regnskapet"]) > REGISTER_CHECK * nxt["regnskapet"]:
            warnings.append(
                texts.register_against_accounts(invoiced, nxt))
    a["fakturering_per_maned"] = invoicing
    a["annen_fakturering"] = runs.other_measured
    a["fast_fakturering_vanlig_mnd"] = round(
        sum(f.get("usual", f["amount"]) for f in runs.found if not f.get("excluded")), 2)
    a["kostnader_per_maned"] = months["costs"]


def _declare_receivables(data: dict, src: Sources, ar_due: list, ar_at_risk: list,
                         ar_doubtful: list, ages: dict, residual: float,
                         counted: bool) -> None:
    """The open invoices as the cards and the clean-up list read them."""
    a = data["assumptions"]
    # What is still owed after the bank's unbooked receipts: a customer who
    # has paid must not be sent a reminder because the books are behind.
    data["ar_open"] = ar_due
    # Invoices to customers in trouble, held out or not, for their cards; and
    # what could not be checked, for the clean-up list.
    data["ar_at_risk"] = ar_at_risk
    data["ar_doubtful"] = ar_doubtful
    a["ukjente_fordringer"] = {
        "belop": round(residual, 2),
        "behandlet": ("forventet" if counted else "ikke_regnet_med") if residual else None}
    a["forfalte_grupper"] = {k: round(v, 2) for k, v in ages.items()}
    data["register"] = brreg.loose_ends({i["name"] for i in src.ar_open})
    # Whether that list is the whole book. An empty list from a failed call
    # reads exactly like a book with nobody late, and cards.py closes every
    # collections card on the strength of it unless told otherwise.
    data["ar_complete"] = src.ar_complete
    # A forecast missing a register is not a forecast, and holding one for the
    # full ten minutes is how a two-second Tripletex blip becomes ten minutes
    # of a company being told it has no receivables. `Cached` keeps a degraded
    # build only long enough to stop a stampede, then goes and asks again.
    data["partial"] = not (src.ar_complete and src.ap_complete)


def _keep(data: dict, rows: list, today: date) -> None:
    """Kept, so it can be scored against what the bank later shows (card 5),
    and the forecasts from 1, 2 and 4 weeks ago scored now if they can be.
    Neither is allowed to cost the forecast itself."""
    try:
        forecasts.record(data, bankgap.ledger_balances(rows), today)
    except Exception:  # noqa: BLE001
        log.exception("Kunne ikke lagre prognosen")
    try:
        scoring.score(today)
    except Exception:  # noqa: BLE001
        log.exception("Kunne ikke score prognosene")
