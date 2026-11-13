"""The forecast assembled: every source read, every flow scheduled."""
import logging
import asyncio
import statistics
from calendar import monthrange
from datetime import date, timedelta

import bankcat
import bankgap
import brreg
import commitments
import company
import forecasts
import payment_habits
import saldobalanse
import scoring
import workdays
from preflight import _monthly, _rows

from . import sources
from .common import AGA_ACCRUED, BANK_UNKNOWN_MAX, DOUBTFUL_DAYS, LATE_DAYS, MONTH_NAMES, MVA_RATE, OPEX_RANGES, PAY_LAG_DAYS, SEASON_WEIGHT, SLOW_WEEKS, VAT_ACCRUED, WEEKS, _kr, _monday
from .payables import _schedule_payments
from .receivables import _days_overdue, _expected_items, _schedule_receipts
from .costs import _bank_costs, _cost_parts, _cost_profile, _fixed_bills
from .invoicing import _invoice_runs, _other_invoicing, _register_months, _sales_profile
from .ledger import _closing_or_none, _run_rates, _seasons
from .tax import _settled, _vat_input_share
from .payroll import _pay_days, _payroll_runs
from .sources import _open_invoices, _tax_postings
from .assemble import _assemble, _bank_payload

log = logging.getLogger("cfo.cashflow")


# No WITHHOLDING_SHARE any more. Until 2026 the tax withheld from wages was held
# back and settled on a bimonthly term, so only the net left on pay day. From
# 2026 there is no skattetrekkskonto and the trekk goes to Skatteetaten the same
# day as the salary — so what leaves the account on pay day is the gross.
# No TRAILING_MONTHS either: it said the run-rates used a trailing window, and
# they never did — `_run_rates` takes a median over every closed month. A
# constant that documents behaviour the code does not have is worse than none.
# The fewest closed months a run-rate is allowed to rest on. Before April this
# year has fewer, and the gap is made up from the end of last year.
MIN_CLOSED_MONTHS = 3
# The register is read for this many closed months before it is trusted over
# the revenue in the accounts; a younger book keeps the old reading.
RUN_MIN_MONTHS = 3
# The register and the accounts are compared on next month: further apart than
# this, the forecast says so rather than choosing between them.
REGISTER_CHECK = 0.35

# Taken from commitments.py, which already dates them. Wages and supplier bills
# are excluded there and modelled here instead — counting both would charge the
# same krone twice.
#
# `annen_gjeld` is here because nothing else carries it: 2990/2991 is never
# invoiced, so the payables list cannot see it, and it was leaving the forecast
# entirely. `leverandorgjeld` stays out, being the payables list's own job, and
# `skyldig_lonn` stays out because the pay-day run already pays it.
#
# `ansatte_eiere` is deliberately NOT here. commitments dates it to today, but
# that is an assumption about undated debt, not a fact — money owed to the owner
# is usually not demand debt, and scheduling 38 000 kr out of this week would
# raise an alarm the ledger does not support. Named so the gap is a decision.
STATUTORY_FROM_COMMITMENTS = {
    "mva_oppgjor", "mva_lopende", "mva_forrige_termin", "aga", "aga_ferie",
    "feriepenger", "betalbar_skatt", "arets_skatt",
    "annen_gjeld",
}
# `forskuddstrekk` is deliberately NOT here, and that is a change of mind.
# Until 2026 the trekk sat on a restricted account and was settled on its own
# term, so scheduling the 2600-2619 balance was right. From 2026 it leaves
# with the salary, and `_payroll_runs` pays the gross — so taking the balance
# as well paid the same krone twice, once on pay day and once at the term.
# Latent rather than live: 2600 has stood at 0 every month of 2026 and 1950
# was closed, which is the regime change showing up in the ledger. Left out so
# it cannot come back the day someone posts to 2600 again.


async def build(today: date | None = None) -> dict:
    today = today or date.today()
    week0 = _monday(today)
    horizon = week0 + timedelta(weeks=WEEKS)
    start_year = f"{today.year}-01-01"

    # The current month is not closed, so January has none of this year's.
    keep = max(0, MIN_CLOSED_MONTHS - (today.month - 1))
    last_year = today.year - 1

    # Last year always: early in the year for the months this year lacks,
    # and every month for the seasonal pattern.
    async def _prior():
        return await saldobalanse.monthly(sources.mcp, f"{last_year}-01-01", f"{last_year}-12-31")

    issued: dict = {}
    supplier_history: list = []
    customer_history: list = []
    balance, com, ar, ap, prior, paid, wages_paid, tax_posts = await asyncio.gather(
        saldobalanse.monthly(sources.mcp, start_year, today.isoformat()),
        commitments.cached(),
        _open_invoices(today, "search_invoices", "Kundefakturaer", "id",
                       "amountOutstanding", "customerName", issued,
                       # Kroner already, for a foreign-currency invoice too.
                       in_kroner=True, history=customer_history),
        # Supplier rows are keyed by voucherId, not id.
        _open_invoices(today, "search_supplier_invoices", "Leverandørfakturaer",
                       "voucherId", "outstandingAmount", "supplierName",
                       history=supplier_history),
        _prior(),
        payment_habits.payments(sources.mcp, today),
        sources._payroll_measured(today),
        _tax_postings(today),
        return_exceptions=True,
    )
    if isinstance(balance, Exception):
        raise RuntimeError(f"Kunne ikke lese saldobalansen: {balance}")
    warnings: list[str] = []
    if isinstance(com, Exception):
        raise RuntimeError(f"Kunne ikke lese forpliktelsene: {com}")
    ar_open, ar_warn, ar_complete = ([], ["Kundefakturaer kunne ikke hentes."], False) \
        if isinstance(ar, Exception) else ar
    ap_open, ap_warn, ap_complete = ([], ["Leverandørfakturaer kunne ikke hentes."], False) \
        if isinstance(ap, Exception) else ap
    warnings += ar_warn + ap_warn

    rows = _rows(balance)
    columns = [c.get("name") for c in balance.get("table", {}).get("columns", [])]
    prior_months = None
    if keep:
        if isinstance(prior, dict) and "table" in prior:
            prior_months = (_rows(prior),
                            [c.get("name") for c in prior["table"].get("columns", [])],
                            last_year, keep)
            warnings.append(
                f"Det er for tidlig på året til å regne løpende tall på "
                f"{today.year} alene, så de siste {keep} månedene av "
                f"{last_year} er tatt med i snittet.")
        else:
            log.warning("Cashflow: fjorårets saldobalanse feilet: %s", prior)
            warnings.append(
                f"Saldobalansen for {last_year} kunne ikke hentes, så de "
                f"løpende tallene hviler på færre enn {MIN_CLOSED_MONTHS} "
                f"måneder.")
    history = None
    if isinstance(prior, dict) and "table" in prior:
        history = (_rows(prior),
                   [c.get("name") for c in prior["table"].get("columns", [])])
    season = _seasons(history)
    # How late each customer pays, from a year of payments on 1500. Without
    # it every customer is the old seven days late, and that is said.
    if isinstance(paid, Exception):
        log.warning("Cashflow: innbetalingene kunne ikke leses: %s", paid)
        paid = None
    habits = payment_habits.habits(customer_history, paid)
    # Every bank line with a category, once a day (card 63): what actually
    # left the account, for the costs (card 64) and for the owner to see.
    bank_categories = await bankcat.measured(
        sources.mcp, today, {r.get("customerName") or "" for r in customer_history})
    if paid is None or not habits["complete"]:
        warnings.append(
            "Innbetalingene på konto 1500 kunne ikke leses helt, så "
            "betalingsvanene er ufullstendige; kunder uten nok historikk er "
            f"regnet med {PAY_LAG_DAYS} dager etter forfall.")
    rates, rate_notes = _run_rates(rows, columns, prior_months, season,
                                   (*history, last_year) if history else None)
    warnings += rate_notes

    def revenue_in(month_no: int) -> float:
        return rates["revenue"] * ((season.get("revenue") or {}).get(month_no, 1.0))

    def opex_in(month_no: int) -> float:
        return rates["opex"] * ((season.get("opex") or {}).get(month_no, 1.0))

    # Open on the money in the bank, not on the booked balance. The bank feed
    # runs days ahead of the bookkeeping, and every week of the forecast, the
    # low point with it, was shifted down by whatever had landed unposted.
    # Measured in commitments, so the forecast and "how much of this is mine"
    # open on the same figure.
    gap = com.get("bank_gap")
    booked = com.get("bank_booked", com["bank"])
    opening = com["bank"]
    if gap is None:
        warnings.append(
            "Bankavstemmingen i Tripletex kunne ikke leses, så prognosen "
            "starter på den bokførte banksaldoen. Har det kommet inn eller gått "
            "ut penger som ikke er bokført ennå, er startpunktet feil med så "
            "mye — og det er ukjent hvor mye.")
    else:
        warnings += gap["unknown"]
        # The figure is right as of the last imported line, so that date is
        # said whenever the feed is behind the last working day.
        if gap.get("stale"):
            warnings.append(
                f"Bankfeeden i Tripletex har ingenting etter {gap['latest']}, "
                f"så startsaldoen er pengene i banken per den dagen. Det som "
                f"har kommet inn eller gått ut siden, er ikke med.")
        if gap["approximate"]:
            warnings.append(
                "For noen måneder i bankavstemmingen fantes ingen bokført "
                "månedsbevegelse å måle mot, så forskjellen mellom bank og bøker "
                "der er regnet ut fra de umatchede listene alene. De utelater "
                "lønnsposteringer brukeren ikke har innsyn i.")

    # A payment the bank has and the ledger has not is still an open invoice
    # in the register. With the opening lifted by that payment, scheduling the
    # invoice as well collects the same krone twice — so what the unbooked
    # lines have paid comes off the lists the schedules are built from. The
    # full lists stay for the reconciliations against 1500 and 2400 below,
    # which compare the register with the ledger and must see what the
    # ledger sees, and for this month's invoicing, which is invoicing whether
    # or not it has been paid.
    # Only what the books do not have: a line booked but not matched in the
    # reconciliation has closed its invoice already (`bankgap.unbooked`).
    unbooked = (bankgap.unbooked(gap["unbooked"], gap.get("booked_unmatched") or [])
                if gap else [])
    ar_due, ar_paid = bankgap.settle(ar_open, unbooked, +1)
    ap_due, ap_paid = bankgap.settle(ap_open, unbooked, -1)

    # Customers Enhetsregisteret has in trouble, as of the last morning check.
    # A bankrupt customer's invoices are not money coming in: they leave the
    # schedule and are carried beside it, for the card that says so. One under
    # voluntary liquidation usually pays, and stays.
    risky = brreg.at_risk()
    # Said on the customer's card, not among the warnings: those are what the
    # regnskapsfører has to fix, and this is nothing in the books.
    ar_at_risk = [{**i, "register": risky[i["name"]]} for i in ar_due if i["name"] in risky]
    ar_due = [i for i in ar_due if not risky.get(i["name"], {}).get("excluded")]

    # The open ledger should agree with the invoice list. Where it does not,
    # the forecast is built on the invoices and the gap is declared.
    # Read with the same carry-forward the rest of the module uses. Requiring
    # the *last* cell to be numeric switched this whole reconciliation off in
    # any month where the account had not moved — a blank cell means unchanged,
    # not zero, as `_monthly` says in as many words — and a silent skip here
    # drops the residual from the forecast and the warning from the answer.
    # The range, not 1500 alone: receivables posted to 1501 and up belong to
    # the same reconciliation, and `commitments` already treats them as one.
    gl_ar = _closing_or_none(rows, 1500, 1509)
    ar_total = sum(i["amount"] for i in ar_open)
    ar_residual = 0.0
    residual_counted = False
    if gl_ar is not None and gl_ar - ar_total > 1000:
        # The invoice list is short of the ledger. It used to be counted as
        # money in, in the committed line, over the next three weeks — money
        # nobody could explain, propping up the floor the colour rests on,
        # while the supplier side pays its unexplained difference this week.
        # What it usually is: invoices older than the lookback (past ninety
        # days by then), postings made straight to 1500, payments not matched
        # to their invoices. Only a list cut off at a hundred rows gives a
        # reason to think it is ordinary invoicing on its way in — that, or a
        # register that could not be read whole; then it is
        # expected, slowly, like the invoices a month or two late. Otherwise it
        # is in neither line, and named, as the oldest invoices are.
        ar_residual = gl_ar - ar_total
        list_short = bool(issued.get("truncated")) or not ar_complete
        residual_counted = list_short
        head = (f"Konto 1500 viser {_kr(gl_ar)} kr i kundefordringer, men de "
                f"åpne fakturaene summerer bare til {_kr(ar_total)} kr. ")
        warnings.append(
            head + (f"Fakturalista er ikke lest helt, så de resterende "
                    f"{_kr(ar_residual)} kr er trolig vanlige fakturaer som ikke "
                    f"ble lest. De ligger bare i den forventede linjen, fordelt "
                    f"over uke {SLOW_WEEKS[0]}–{SLOW_WEEKS[1]}."
                    if residual_counted else
                    f"De resterende {_kr(ar_residual)} kr er ikke regnet med i "
                    f"prognosen før noen har funnet ut hva de består av — "
                    f"gamle fakturaer, posteringer rett på kontoen eller "
                    f"innbetalinger som ikke er koblet til fakturaen."))

    committed: list[dict] = []
    expected: list[dict] = []

    receipts = _schedule_receipts(ar_due, today, habits)
    committed += [f for f in receipts if f["kind"] != "ar_slow"]
    expected += [f for f in receipts if f["kind"] == "ar_slow"]
    # The ones not counted on at all, named so they are chased.
    ar_doubtful = [{**i, "days_overdue": _days_overdue(i, today)} for i in ar_due
                   if (_days_overdue(i, today) or 0) > DOUBTFUL_DAYS]
    ar_doubtful.sort(key=lambda i: -i["amount"])
    ages = {"i_rute": 0.0, "inntil_30": 0.0, "31_90": 0.0, "over_90": 0.0}
    for i in ar_due:
        late = _days_overdue(i, today)
        if late is None:
            continue
        key = ("i_rute" if late == 0 else "inntil_30" if late <= LATE_DAYS
               else "31_90" if late <= DOUBTFUL_DAYS else "over_90")
        ages[key] += i["amount"]
    if ar_residual and residual_counted:
        first, last = SLOW_WEEKS
        per = ar_residual / (last - first + 1)
        for w in range(first, last + 1):
            expected.append({"date": today + timedelta(days=7 * w),
                             "amount": per, "kind": "ar_unmatched",
                             "label": "Kundefordringer uten kjent faktura, "
                                      "trolig fra en avkortet fakturaliste"})
    committed += _schedule_payments(ap_due, today)
    # Rent, leasing, insurance: certain whether anyone sells anything, so the
    # floor carries them. The expected line's running costs already contain
    # them, and are netted below month by month.
    fixed_flows, fixed_found, fixed_by_month = _fixed_bills(
        supplier_history, today, horizon)
    committed += fixed_flows
    profile = _cost_profile(supplier_history, {f["name"] for f in fixed_found})
    # And the sales not yet invoiced: when in the month this company invoices,
    # on what terms, paid as late as its customers usually pay.
    sales_profile = _sales_profile(customer_history)
    sales_lag = (habits["company"] if habits.get("company") is not None
                 else PAY_LAG_DAYS)
    # The customers on a contract are invoiced whether or not anyone sells
    # anything, so the floor carries them, as it carries the rent — with the
    # VAT and the running costs that serving them brings, in the loop below.
    # Not those in trouble with the register, nor those already further behind
    # than ordinary lateness: their open invoices are not counted on either.
    # What each customer has over LATE_DAYS late. It used to be a set of
    # names, and any one invoice in it took the customer out of both lines.
    behind: dict[str, float] = {}
    for i in ar_due:
        if (_days_overdue(i, today) or 0) > LATE_DAYS:
            behind[i["name"]] = behind.get(i["name"], 0.0) + i["amount"]
    run_flows, recurring_found, run_by_month = _invoice_runs(
        customer_history, today, horizon, habits, season.get("revenue"),
        set(risky), behind)
    committed += [f for f in run_flows if f["kind"] == "recurring"]
    # With RUN_MIN_MONTHS of invoicing to read, the register is the money
    # coming in, and the revenue in the accounts only a check on it. The
    # accounts × 1.25 put a month's sales on one profile for the whole
    # company, and at the first customer the chart read as if invoicing had
    # stopped. A book younger than that keeps the accounts.
    from_register = _register_months(customer_history, today) >= RUN_MIN_MONTHS
    other_by_month, other_measured = {}, None
    if from_register:
        expected += [f for f in run_flows if f["kind"] == "recurring_usual"]
        other_flows, other_by_month, other_measured = _other_invoicing(
            customer_history, today, horizon, sales_lag, season.get("revenue"),
            {f["name"] for f in recurring_found}, set(risky))
        expected += other_flows

    # The same check as on 1500 above, which 2400 never had — and the asymmetry
    # was backwards. Being short on receivables flatters the forecast; being
    # short on payables hides money going out, and that is the side nobody
    # noticed was empty for as long as the supplier search read the wrong key.
    # A liability is a credit balance, so what is owed is the balance negated.
    gl_ap_raw = _closing_or_none(rows, 2400, 2409)
    gl_ap = None if gl_ap_raw is None else -gl_ap_raw
    ap_total = sum(b["amount"] for b in ap_open)
    if gl_ap is not None and gl_ap - ap_total > 1000:
        residual = gl_ap - ap_total
        # Dated to this week, not spread like the receivables. An undated bill
        # is already late more often than it is early, and the overdue book
        # must not be made to look further away than it is.
        committed.append({"date": today, "amount": -residual,
                          "kind": "ap_unmatched",
                          "label": "Leverandørgjeld uten kjent faktura"})
        warnings.append(
            f"Konto 2400 viser {_kr(gl_ap)} kr i leverandørgjeld, men de åpne "
            f"leverandørfakturaene summerer bare til {_kr(ap_total)} kr. De "
            f"resterende {_kr(residual)} kr er lagt inn denne uka, uten "
            f"forfallsdato å feste dem til. Noen bør finne ut hva de består av.")
    elif gl_ap is not None and ap_total - gl_ap > 1000:
        # The other direction, and it is not symmetrical. Here the register
        # claims more is outstanding than the ledger says is owed, so the
        # forecast pays bills the books consider settled. It is NOT trimmed to
        # the ledger: the invoices carry real due dates and the difference has
        # no one invoice to take it from, so capping would mean choosing which
        # supplier to stop paying. Said out loud instead, and left standing —
        # paying too early is the survivable mistake of the two.
        warnings.append(
            f"De åpne leverandørfakturaene summerer til {_kr(ap_total)} kr, "
            f"men konto 2400 viser bare {_kr(gl_ap)} kr i leverandørgjeld. "
            f"Prognosen betaler ut hele {_kr(ap_total)} kr, altså "
            f"{_kr(ap_total - gl_ap)} kr mer enn bøkene sier dere skylder. "
            f"Som regel er det fakturaer som er betalt uten at restbeløpet ble "
            f"nullet i reskontroen. Verdt å rydde i.")

    for item in com["items"]:
        if item["id"] not in STATUTORY_FROM_COMMITMENTS:
            continue
        try:
            due = date.fromisoformat(item["due"])
        except (ValueError, TypeError):
            continue
        committed.append({"date": max(due, today), "amount": -item["amount"],
                          "kind": "statutory", "label": item["label"]})

    # What this month's payroll has already put on 2770, if it has been run
    # and posted. A liability is a credit balance, so an accrual is negative.
    # Without the postings nothing is taken off the movement, as before.
    if isinstance(tax_posts, Exception):
        log.warning("Cashflow: månedens mva- og aga-posteringer kunne ikke leses: %s",
                    tax_posts)
        tax_posts = []
    vat_settled, aga_paid = _settled(tax_posts)
    aga_series = _monthly(rows, columns, *AGA_ACCRUED)
    aga_booked = max(0.0, -(aga_series[-1][1] - aga_paid)) if aga_series else 0.0
    # What a pay day really pays, where the payroll vouchers say so; the wage
    # accounts otherwise.
    if isinstance(wages_paid, dict) and "unread" in wages_paid:
        warnings.append(
            "Lønnsbilagene kunne ikke leses, så lønningsdagen er regnet fra "
            "lønnskontoene i stedet for det tidligere lønningsdager har betalt. "
            "Det kan være for mye, fordi kontoene også har periodisering og "
            "feriepenger i seg.")
    wages_paid = wages_paid if isinstance(wages_paid, dict) and "per_run" in wages_paid else None
    pay_day_cash = wages_paid["per_run"] if wages_paid else rates["wages_cash"]
    # The bank figure is as of its last line, not today: a pay day after it is
    # still to go out, as commitments dates the taxes.
    try:
        paid_before = date.fromisoformat(com.get("paid_before") or "")
    except ValueError:
        paid_before = today
    committed += _payroll_runs(today, horizon, pay_day_cash,
                               rates["aga"], aga_booked, paid_before)
    payroll_months = [m for _, m, _ in _pay_days(today, horizon, paid_before)]

    # Trading that has not happened yet: invoicing goes out at month end and is
    # collected on the terms this company's customers actually take. Running
    # costs are charged from next month, since this month's bills are already
    # in the payables above.
    terms = [(date.fromisoformat(i["due"]) - date.fromisoformat(i["invoiced"])).days
             for i in ar_open if i.get("invoiced") and i.get("due")]
    # What the customers' own invoices say first; the company's stated terms
    # where there are none to measure; 30 days only where neither exists.
    stated_terms = company.setting("kredittid_dager")
    if terms:
        credit_days, credit_source = int(statistics.median(terms)), "målt på fakturaene"
    elif stated_terms and 0 < int(stated_terms) <= 365:
        credit_days, credit_source = int(stated_terms), "fra company.md"
    else:
        credit_days, credit_source = 30, "antatt"
    vat_share, vat_measured = _vat_input_share(rows)
    # What this month has already accrued. commitments dates the whole
    # 2700-2739 balance to the running term's deadline, and the loop below
    # adds a full month's VAT for the current month on that very same date —
    # so everything already booked was being paid twice, by a margin that
    # grows through the month to nearly a full month's VAT by the end of it.
    # Only the part still to be invoiced belongs here. A liability is a credit
    # balance, so an accrual shows up as a negative movement; `commitments`
    # negates the same way when it turns a balance into an amount owed.
    booked_vat = 0.0
    vat_series = _monthly(rows, columns, *VAT_ACCRUED)
    if vat_series:
        booked_vat = max(0.0, -(vat_series[-1][1] - vat_settled))
    # The same overlap on the way in. Invoicing already issued this month sits
    # in ar_open with a real due date of its own; forecasting a full month on
    # top of it collects the same krone twice. The opex leg three lines down
    # has always guarded this ("this month's bills are already in the payables
    # above") — the revenue leg never did. Gross against gross: amounts here
    # are what the customer owes, and so is revenue × (1 + MVA_RATE).
    invoiced_this_month = 0.0
    for i in ar_open:
        try:
            issued_on = date.fromisoformat(i["invoiced"])
        except (ValueError, TypeError, KeyError):
            continue
        if (issued_on.year, issued_on.month) == (today.year, today.month):
            invoiced_this_month += i["amount"]
    # Everything invoiced this month, paid ones included. The open list above
    # has only what is still owed, so an invoice sent on the 2nd and paid on
    # the 9th was not netted off: its money was in the opening balance and
    # collected again at month end. The open list stays the floor, for a
    # month whose invoices could not be read.
    invoiced_this_month = max(invoiced_this_month, issued.get("this_month", 0.0))
    # Running costs leave the account with their VAT on, and the run-rate is
    # the P&L figure, which has none. The VAT forecast above takes the input
    # VAT off what is paid over, so leaving it off the bills as well took the
    # deduction without ever paying the VAT it deducts. Added back as exactly
    # that deduction rather than 25 % on every cost account: pension,
    # insurance and bank fees carry none, and the deduction is already the
    # measured share. Unmeasured, it is zero on both sides.
    opex_vat = rates["revenue"] * MVA_RATE * vat_share
    opex_cash = rates["opex"] + opex_vat
    # Per month from here, each on its own season: the VAT on the bills
    # follows the deduction, which follows the month's sales.
    # What this month has already booked against the same cost accounts. The
    # opex leg used to start next month on the strength of "this month's bills
    # are already in the payables" — true on the last day of the month only.
    # On the 5th most of the month's bills have not arrived, and they were in
    # no line at all. Netted the way the revenue leg nets what is invoiced: a
    # bill booked this month is in the payables or already paid out of the
    # opening balance, and one still in the inbox is in neither, so it belongs
    # to the remainder. Net against net; the VAT goes on after.
    booked_opex = 0.0
    for low, high in OPEX_RANGES:
        series = _monthly(rows, columns, low, high)
        if series:
            booked_opex += series[-1][1]
    booked_opex = max(0.0, booked_opex)
    opex_left = max(0.0, opex_in(today.month) - booked_opex)
    # The running costs from the bank, where it can be read and most of what
    # leaves it has a category (card 64). The accounts are only as current as
    # the bookkeeping: at the first customer they gave the forecast about a
    # third less than left the bank, and nothing for loan instalments.
    bank_costs = _bank_costs(bank_categories)
    if bank_categories and not bank_costs:
        warnings.append(
            "Driftskostnadene er regnet fra regnskapet, ikke fra banken: "
            + ("for mange utbetalinger i banken har ingen kategori ennå "
               f"({round(bank_categories.get('unknown_share_out', 0) * 100)} %)."
               if bank_categories.get("unknown_share_out", 0) > BANK_UNKNOWN_MAX
               else f"færre enn {bankcat.COST_MIN_MONTHS} hele måneder å lese."))
    # What is already dated in each month and is part of the same money out:
    # the open bills, the fixed bills, and the bills booked without one.
    known_by_month: dict = {}
    for f in committed:
        if f["kind"] in ("ap", "fixed", "ap_unmatched"):
            key = (f["date"].year, f["date"].month)
            known_by_month[key] = known_by_month.get(key, 0.0) - f["amount"]
    sales_by_month, costs_by_month, invoicing_by_month = [], [], []
    month = date(today.year, today.month, 1)
    for _ in range(6):
        month_end = date(month.year, month.month, monthrange(month.year, month.month)[1])
        revenue = revenue_in(month.month)
        opex = opex_in(month.month)
        sales_by_month.append({"month": MONTH_NAMES[month.month - 1],
                               "amount": round(revenue, 2)})
        costs_by_month.append({"month": MONTH_NAMES[month.month - 1],
                               "amount": round(bank_costs["level"] if bank_costs else opex, 2)})
        month_vat = revenue * MVA_RATE * vat_share
        gross = revenue * (1 + MVA_RATE)
        if (month.year, month.month) == (today.year, today.month):
            gross = max(0.0, gross - invoiced_this_month)
        current = (month.year, month.month) == (today.year, today.month)
        run = run_by_month.get((month.year, month.month), {"low": 0.0, "usual": 0.0})
        # The contract customers' part of the month is in the committed line
        # already, each on his own dates; what is left here is the invoicing
        # still to be won. The same share of the VAT and of the running costs
        # moves with it: a contract costs materials and fuel to serve like any
        # other sale, and a floor that took the money without the cost would
        # stand higher than it is.
        contract = run["low"]
        if from_register:
            # Everything still to be invoiced this month and after, from the
            # register: the regular customers at their usual month and the
            # rest at its median. Already on the weeks above; here only for
            # the VAT and the share of the running costs.
            other = other_by_month.get((month.year, month.month), 0.0)
            gross = run["usual"] + other
            invoicing_by_month.append({
                "month": MONTH_NAMES[month.month - 1],
                "fast_lavest": round(run["low"], 2), "fast_vanlig": round(run["usual"], 2),
                "annen": round(other, 2), "regnskapet": round(revenue * (1 + MVA_RATE), 2)})
        tied = min(1.0, contract / gross) if gross > 0 else (1.0 if contract else 0.0)
        gross = max(0.0, gross - contract)
        if from_register:
            parts = []
        elif sales_profile.get("measured"):
            # Each period's share, paid its own terms plus the lateness after.
            # This month's remainder only in the days still to come.
            parts = [(pay + timedelta(days=sales_lag), share, days)
                     for pay, share, days in _cost_parts(sales_profile, month,
                                                         today, current)]
        else:
            parts = [(month_end + timedelta(days=credit_days + sales_lag), 1.0, "")]
        for landing, share, days in parts:
            amount = gross * share
            if today <= landing < horizon and round(amount) > 0:
                expected.append({"date": landing, "amount": amount,
                                 "kind": "new_sales",
                                 "label": f"Fakturering {MONTH_NAMES[month.month - 1]}"
                                          f"{', ' + days.replace('fakturert ', '') if days else ''}"
                                          f", betalt"})
        # The VAT on that invoicing, whether or not the customer has paid by
        # then — the deadline does not wait for the money. Scheduled even when
        # the receipt itself falls outside the window, because that is the case
        # that hurts: the liability inside, the cash outside.
        net_vat = revenue * MVA_RATE * (1 - vat_share)
        if from_register:
            # On what is still to be invoiced. What has gone out this month
            # is booked on 2700 already, and dated by commitments.
            net_vat = (gross + contract) / (1 + MVA_RATE) * MVA_RATE * (1 - vat_share)
        elif (month.year, month.month) == (today.year, today.month):
            net_vat = max(0.0, net_vat - booked_vat)
        contract_vat = contract / (1 + MVA_RATE) * MVA_RATE * (1 - vat_share)
        net_vat = max(0.0, net_vat - contract_vat)
        vat_due = workdays.forward(
            commitments.term_due(month.year, month.month, commitments.MVA_TERMS))
        if today <= vat_due < horizon and round(contract_vat) > 0:
            committed.append({"date": vat_due, "amount": -contract_vat,
                              "kind": "vat_recurring",
                              "label": f"Merverdiavgift på fast fakturering "
                                       f"{MONTH_NAMES[month.month - 1]}"})
        if today <= vat_due < horizon and round(net_vat) > 0:
            expected.append({"date": vat_due, "amount": -net_vat,
                             "kind": "vat_future",
                             "label": f"Merverdiavgift på fakturering "
                                      f"{MONTH_NAMES[month.month - 1]}"})
        if bank_costs:
            # From the bank (card 64): the usual month of what left the
            # account, gross, by the day it left. What is dated already in the
            # same month — open bills, fixed bills, and this month what has
            # left the bank — is part of that month, so it comes off.
            key = (month.year, month.month)
            fixed = known_by_month.get(key, 0.0)
            cost = max(0.0, bank_costs["level"] - fixed
                       - (bank_costs["paid_this_month"] if current else 0.0))
            cost_tied = bank_costs["certain_share"] + (1 - bank_costs["certain_share"]) * tied
            cost_parts = _cost_parts(bank_costs["profile"], month, today, current)
            month_vat = 0.0
        else:
            cost = (opex_left * ((opex + month_vat) / opex) if opex else 0.0) \
                if current else opex + month_vat
            # The fixed bills of this month are its cost too, placed in the
            # committed line on their own dates when they fall inside the window.
            # Both gross. Never below zero: fixed bills above the run-rate mean
            # the rate is low, not that money comes back.
            fixed = fixed_by_month.get((month.year, month.month), 0.0)
            cost = max(0.0, cost - fixed)
            cost_tied = tied
            cost_parts = _cost_parts(profile, month, today, current)
        # Spread by when the bills are paid. A part paid after the window
        # leaves it, as sales collected after it do.
        for pay, share, days in cost_parts:
            part = cost * share
            if pay >= horizon or round(part) <= 0:
                continue
            if bank_costs:
                label = (f"Driftskostnader {MONTH_NAMES[month.month - 1]}"
                         f"{', resten' if current else ''}"
                         f"{', betalt ' + days.replace('fakturert ', '') if days else ''}"
                         f", fra banken"
                         f"{' utenom kjente regninger' if fixed >= 0.5 else ''}")
            else:
                label = (f"Driftskostnader {MONTH_NAMES[month.month - 1]}"
                         f"{', resten' if current else ''}"
                         f"{', ' + days if days else ''}"
                         f"{' utenom faste regninger' if fixed >= 0.5 else ''}"
                         f"{' (inkl. moms)' if month_vat >= 0.5 else ''}")
            # From the bank the committed part is also what comes whatever is
            # sold: rent, loans, insurance, pension, fees, the accountant.
            sure = (", den faste delen" if bank_costs
                    else ", til den faste faktureringen")
            if round(part * cost_tied) > 0:
                committed.append({"date": pay, "amount": -part * cost_tied,
                                  "kind": "opex_recurring", "label": label + sure})
            if round(part * (1 - cost_tied)) > 0:
                expected.append({"date": pay, "amount": -part * (1 - cost_tied),
                                 "kind": "opex", "label": label})
        month = (date(month.year + 1, 1, 1) if month.month == 12
                 else date(month.year, month.month + 1, 1))

    if not vat_measured:
        warnings.append(
            "Forholdet mellom utgående og inngående merverdiavgift lot seg "
            "ikke måle — konto 2700 er tom eller nettopp gjort opp. Prognosen "
            "legger derfor ut hele den utgående momsen på ny fakturering, uten "
            "fradrag for moms på det dere selv kjøper. Det er for strengt, ikke "
            "for snilt, men det er verdt å vite.")

    data = _assemble(today, week0, opening, committed, expected,
                     rates, credit_days, warnings, ar_due, ap_due,
                     vat_share, vat_measured, booked_vat,
                     invoiced_this_month, payroll_months)
    data["assumptions"]["credit_days_source"] = credit_source
    data["assumptions"]["lonn_per_lonningsdag"] = {
        "belop": round(pay_day_cash, 2),
        "kilde": "lønnsbilagene" if wages_paid else "lønnskontoene",
        "maneder": (wages_paid or {}).get("months", [])}
    # What the bills cost in cash, against the P&L figure beside it, and what
    # this month has already booked — netted off, as `fakturert_denne_maneden`.
    data["assumptions"]["mva_paa_kostnader"] = round(opex_vat, 2)
    data["assumptions"]["monthly_opex_cash"] = round(opex_cash, 2)
    data["assumptions"]["kostnader_bokfort_denne_maneden"] = round(booked_opex, 2)
    # Where the running costs came from, and from the bank what they rest on.
    data["assumptions"]["kostnader_kilde"] = "banken" if bank_costs else "regnskapet"
    data["assumptions"]["kostnader_fra_banken"] = bank_costs and {
        "nivaa_mnd": bank_costs["level"],
        "maneder": bank_costs["months"],
        "andeler": bank_costs["shares"],
        "sikker_andel": bank_costs["certain_share"],
        "betalt_denne_maneden": bank_costs["paid_this_month"]}
    # The recurring bills the committed line now carries, for the owner to
    # check against what he knows he pays.
    data["fixed_costs"] = fixed_found
    # And the contract customers it now counts on, for the same check: he
    # knows which buildings are on a monthly contract better than we do.
    data["recurring_sales"] = recurring_found
    data["assumptions"]["fast_fakturering_mnd"] = round(
        sum(f["amount"] for f in recurring_found), 2)
    data["assumptions"]["kostnadsprofil"] = profile
    data["assumptions"]["fakturaprofil"] = {**sales_profile, "forsinkelse_dager": sales_lag}
    data["assumptions"]["sesong"] = {
        k: ({MONTH_NAMES[m - 1]: v for m, v in sorted(idx.items())} if idx else None)
        for k, idx in season.items()}
    data["assumptions"]["sesong_vekt"] = SEASON_WEIGHT
    data["assumptions"]["omsetning_per_maned"] = sales_by_month
    data["assumptions"]["fakturering_fra"] = "fakturaregisteret" if from_register else "regnskapet"
    # The accounts as a check on the register, on next month: the whole of it
    # is still to be invoiced, so the two should tell the same story.
    nxt = invoicing_by_month[1] if len(invoicing_by_month) > 1 else None
    if nxt and nxt["regnskapet"] > 0:
        invoiced = nxt["fast_vanlig"] + nxt["annen"]
        if abs(invoiced - nxt["regnskapet"]) > REGISTER_CHECK * nxt["regnskapet"]:
            warnings.append(
                f"Fakturaene sier {_kr(invoiced)} kr i {nxt['month']} med moms, "
                f"regnskapet {_kr(nxt['regnskapet'])} kr. Prognosen følger "
                f"fakturaene, kunde for kunde. Er forskjellen inntekter som ikke "
                f"faktureres i Tripletex, eller fakturering som har endret seg, "
                f"er det verdt å vite.")
    data["assumptions"]["fakturering_per_maned"] = invoicing_by_month
    data["assumptions"]["annen_fakturering"] = other_measured
    data["assumptions"]["fast_fakturering_vanlig_mnd"] = round(
        sum(f.get("usual", f["amount"]) for f in recurring_found if not f.get("excluded")), 2)
    data["assumptions"]["kostnader_per_maned"] = costs_by_month
    data["assumptions"]["faste_regninger_mnd"] = round(sum(
        f["amount"] / (1 if f["cadence"] == "månedlig" else 3) for f in fixed_found), 2)
    data["bank"] = _bank_payload(booked, gap, ar_paid, ap_paid)
    data["items"] = _expected_items(ar_due, ap_due, today, habits)
    data["betalingsvaner"] = habits
    data["bank_categories"] = bank_categories
    # What is still owed after the bank's unbooked receipts: a customer who
    # has paid must not be sent a reminder because the books are behind.
    data["ar_open"] = ar_due
    # Invoices to customers in trouble, held out or not, for their cards; and
    # what could not be checked, for the clean-up list.
    data["ar_at_risk"] = ar_at_risk
    data["ar_doubtful"] = ar_doubtful
    data["assumptions"]["ukjente_fordringer"] = {
        "belop": round(ar_residual, 2),
        "behandlet": ("forventet" if residual_counted else "ikke_regnet_med")
                     if ar_residual else None}
    data["assumptions"]["forfalte_grupper"] = {k: round(v, 2) for k, v in ages.items()}
    data["register"] = brreg.loose_ends({i["name"] for i in ar_open})
    # Whether that list is the whole book. An empty list from a failed call
    # reads exactly like a book with nobody late, and cards.py closes every
    # collections card on the strength of it unless told otherwise.
    data["ar_complete"] = ar_complete
    # A forecast missing a register is not a forecast, and holding one for the
    # full ten minutes is how a two-second Tripletex blip becomes ten minutes
    # of a company being told it has no receivables. `Cached` keeps a degraded
    # build only long enough to stop a stampede, then goes and asks again.
    data["partial"] = not (ar_complete and ap_complete)
    # Kept, so it can be scored against what the bank later shows (card 5).
    # Saving is never allowed to cost the forecast itself.
    try:
        forecasts.record(data, bankgap.ledger_balances(rows), today)
    except Exception:  # noqa: BLE001
        log.exception("Kunne ikke lagre prognosen")
    # And the forecasts from 1, 2 and 4 weeks ago held against what the bank
    # showed — scored as soon as the figures for it exist, and only once.
    try:
        scoring.score(today)
    except Exception:  # noqa: BLE001
        log.exception("Kunne ikke score prognosene")
    return data
