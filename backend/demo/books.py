"""The books of a made-up company, generated from a description of it.

One double-entry journal is the source of everything: the trial balance, the
P&L, the subledgers and the invoice lists are all read off it, so they tie the
way real books do and the app's own reconciliations pass or fail only where a
company's story says they should.

The year runs from 1 January last year to yesterday, relative to the day the
server starts, so a demo always looks current. Amounts come from a random
generator seeded by the company, so the same company tells the same story.
Debit is positive, credit negative.
"""
import random
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, timedelta

import workdays

ACCOUNTS = {
    1230: "Biler", 1250: "Inventar og maskiner", 1460: "Varelager",
    1500: "Kundefordringer", 1920: "Bedriftskonto",
    2000: "Aksjekapital", 2050: "Annen egenkapital",
    2220: "Gjeld til kredittinstitusjoner", 2400: "Leverandørgjeld",
    2500: "Betalbar skatt", 2600: "Forskuddstrekk",
    2700: "Utgående merverdiavgift", 2710: "Inngående merverdiavgift",
    2740: "Oppgjørskonto merverdiavgift", 2770: "Skyldig arbeidsgiveravgift",
    2940: "Skyldige feriepenger",
    3000: "Salgsinntekt, avgiftspliktig",
    4000: "Innkjøp av råvarer og halvfabrikata",
    4300: "Innkjøp av varer for videresalg",
    4390: "Beholdningsendring varer",
    4500: "Fremmedytelse og underentreprise",
    5000: "Lønn til ansatte", 5020: "Feriepenger", 5400: "Arbeidsgiveravgift",
    5945: "Pensjonsforsikring for ansatte",
    6010: "Avskrivning på transportmidler", 6020: "Avskrivning på inventar",
    6300: "Leie lokale", 6400: "Leie maskiner", 6420: "Leie datasystemer",
    6550: "Driftsmateriale", 6570: "Arbeidsklær og verneutstyr",
    6705: "Honorar regnskap", 6800: "Kontorrekvisita", 6900: "Telefon",
    7000: "Drivstoff, selskapets transportmidler",
    7020: "Vedlikehold, selskapets transportmidler",
    7320: "Reklamekostnad", 7500: "Forsikringspremie",
    7770: "Bank og kortgebyrer",
    8050: "Annen renteinntekt", 8150: "Annen rentekostnad",
    8300: "Betalbar skatt",
}

VAT = 0.25
AGA = 0.141            # arbeidsgiveravgift, sone 1
HOLIDAY = 0.12         # feriepenger, fem uker
PENSION = 0.02         # OTP
WITHHOLDING = 0.31     # forskuddstrekk, snitt
TAX = 0.22

# The terms Norway uses, the same as commitments.py schedules from.
VAT_TERMS = [((1, 2), (4, 10)), ((3, 4), (6, 10)), ((5, 6), (8, 31)),
             ((7, 8), (10, 10)), ((9, 10), (12, 10)), ((11, 12), (2, 10))]
TAX_TERMS = [((1, 2), (3, 15)), ((3, 4), (5, 15)), ((5, 6), (7, 15)),
             ((7, 8), (9, 15)), ((9, 10), (11, 15)), ((11, 12), (1, 15))]


# ------------------------------------------------------------ the description
@dataclass(frozen=True)
class Customer:
    name: str
    share: float              # of the month's revenue
    terms: int = 30           # betalingsfrist, days
    late: float = 2.0         # how late they usually pay, days
    org: str = ""


@dataclass(frozen=True)
class Supplier:
    name: str
    account: int
    monthly: float = 0.0      # net, a fixed bill
    ratio: float = 0.0        # or net as a share of the month's revenue
    terms: int = 30
    day: int = 5              # day of the month the bill is dated
    vat: bool = True


@dataclass(frozen=True)
class Spec:
    slug: str
    name: str
    orgnr: str
    seed: int
    revenue: float            # a normal month's net revenue this year
    season: tuple             # twelve multipliers, January first
    growth: float             # this year over last year
    customers: tuple
    suppliers: tuple
    payroll: float            # payroll cost (wages, holiday pay, AGA, pension) per kr revenue
    headcount: int
    fte: float
    payday: int               # day of the month wages go out
    invoice_day: int          # day of the month the month's invoices go out; 0 = last workday
    opening_bank: float
    opening_assets: float
    opening_stock: float = 0.0
    loan: float = 0.0
    loan_monthly: float = 0.0
    dividend: float = 0.0         # paid to the owners each May
    inbox: int = 0
    budget_revenue: float = 1.0   # budget against actual revenue
    budget_payroll: float = 0.0   # budget payroll share; 0 = actual
    company_md: str = ""
    # The industry profile (state/profile.json): which figures matter and
    # what good looks like. In the real product the model decides it once
    # from the books; a demo brings it decided, the way the model would.
    profile: dict = field(default_factory=dict)
    # Scripted turns of the story, applied after the ordinary months.
    events: tuple = ()


# ------------------------------------------------------------------ the books
@dataclass
class Posting:
    id: int
    voucher: int
    date: date
    account: int
    amount: float
    text: str
    customer: str | None = None
    supplier: str | None = None


@dataclass
class Invoice:
    id: int
    number: int
    date: date
    due: date
    customer: str
    customer_id: int
    net: float
    paid: date | None = None
    comment: str = ""

    @property
    def gross(self) -> float:
        return round(self.net * (1 + VAT), 2)


@dataclass
class Bill:
    id: int
    voucher: int
    number: str
    date: date
    due: date
    supplier: str
    supplier_id: int
    account: int
    net: float
    vat: bool
    paid: date | None = None

    @property
    def gross(self) -> float:
        return round(self.net * (1 + VAT) if self.vat else self.net, 2)


@dataclass
class Books:
    spec: Spec
    today: date
    postings: list = field(default_factory=list)
    invoices: list = field(default_factory=list)
    bills: list = field(default_factory=list)
    customers: dict = field(default_factory=dict)   # name -> {id, number, org}
    suppliers: dict = field(default_factory=dict)
    _voucher: int = 1000

    @property
    def last_day(self) -> date:
        """The newest day in the books: yesterday."""
        return self.today - timedelta(days=1)

    def post(self, on: date, lines: list[tuple[int, float]], text: str,
             customer: str | None = None, supplier: str | None = None) -> int:
        lines = [(a, round(v, 2)) for a, v in lines if abs(v) >= 0.005]
        rest = round(sum(v for _, v in lines), 2)
        if abs(rest) >= 0.005:
            # Rounding lands on the largest line, as a bookkeeper would put it.
            i = max(range(len(lines)), key=lambda k: abs(lines[k][1]))
            lines[i] = (lines[i][0], round(lines[i][1] - rest, 2))
        self._voucher += 1
        for a, v in lines:
            assert a in ACCOUNTS, a
            self.postings.append(Posting(len(self.postings) + 1, self._voucher, on,
                                         a, v, text, customer, supplier))
        return self._voucher

    def _index(self) -> dict:
        """Per account: posting dates in order and the running sum after each,
        so a balance is a binary search, not a pass over the whole journal."""
        if getattr(self, "_idx", None) is None or self._idx_n != len(self.postings):
            idx: dict = {}
            for p in sorted(self.postings, key=lambda p: p.date):
                dates, sums = idx.setdefault(p.account, ([], []))
                dates.append(p.date)
                sums.append((sums[-1] if sums else 0.0) + p.amount)
            self._idx, self._idx_n = idx, len(self.postings)
        return self._idx

    def _upto(self, account: int, before: date) -> float:
        dates, sums = self._index().get(account, ([], []))
        k = bisect_left(dates, before)
        return sums[k - 1] if k else 0.0

    def balance(self, account: int, before: date, year: int | None = None) -> float:
        """The account's balance at the start of `before`. A result account
        counts only its accounting year (`year`, by default the one `before`
        falls in), as Tripletex's restart each 1 January."""
        total = self._upto(account, before)
        if account >= 3000:
            total -= self._upto(account, date(year or before.year, 1, 1))
        return round(total, 2)

    def moved(self, account: int, start: date, end_excl: date) -> bool:
        dates, _ = self._index().get(account, ([], []))
        k = bisect_left(dates, start)
        return k < len(dates) and dates[k] < end_excl


# -------------------------------------------------------------- generation
def _month_days(y: int, m: int) -> int:
    return ((date(y + (m == 12), m % 12 + 1, 1)) - date(y, m, 1)).days


def _on(y: int, m: int, day: int) -> date:
    return date(y, m, min(day, _month_days(y, m)))


def _due(year: int, month: int, terms: list) -> date:
    for months, (dm, dd) in terms:
        if month in months:
            y = year + (dm < months[0])
            return _on(y, dm, dd)
    raise ValueError(month)


def generate(spec: Spec, today: date | None = None) -> Books:
    today = today or date.today()
    b = Books(spec, today)
    rng = random.Random(spec.seed)
    for i, c in enumerate(spec.customers):
        b.customers[c.name] = {"id": 5000 + i, "number": 10001 + i, "org": c.org}
    for i, s in enumerate(spec.suppliers):
        b.suppliers[s.name] = {"id": 7000 + i, "number": 20001 + i}

    start = date(today.year - 1, 1, 1)
    equity = spec.opening_bank + spec.opening_assets + spec.opening_stock - spec.loan
    b.post(start, [(1920, spec.opening_bank), (1230, spec.opening_assets * 0.7),
                   (1250, spec.opening_assets * 0.3), (1460, spec.opening_stock),
                   (2220, -spec.loan), (2000, -100_000), (2050, -(equity - 100_000))],
           "Inngående balanse")

    holiday_owed = {today.year - 2: 0.0}   # earned per year, paid next June
    y, m = start.year, start.month
    while (y, m) <= (today.year, today.month):
        season = spec.season[m - 1]
        level = spec.revenue * season * (1 if y == today.year else 1 / spec.growth)
        last = workdays.backward(_on(y, m, 31))

        # Sales: the month's invoices, and when each customer pays them.
        inv_on = last if spec.invoice_day == 0 else _on(y, m, spec.invoice_day)
        for c in spec.customers:
            net = round(level * c.share * rng.uniform(0.9, 1.1), -2)
            if net <= 0 or inv_on > b.last_day:
                continue
            due = inv_on + timedelta(days=c.terms)
            paid = due + timedelta(days=round(max(-4, rng.gauss(c.late, max(1.0, c.late / 3)))))
            inv = Invoice(len(b.invoices) + 1, 24001 + len(b.invoices), inv_on, due,
                          c.name, b.customers[c.name]["id"], net,
                          paid if paid <= b.last_day else None,
                          f"{_mname(m)} {y}")
            b.invoices.append(inv)

        # Suppliers: a fixed bill, or one that follows the work done.
        for s in spec.suppliers:
            net = s.monthly * rng.uniform(0.96, 1.04) if s.monthly else level * s.ratio * rng.uniform(0.92, 1.08)
            on = _on(y, m, s.day)
            if net <= 0 or on > b.last_day:
                continue
            due = on + timedelta(days=s.terms)
            bill = Bill(len(b.bills) + 1, 0, f"{rng.randint(100000, 999999)}", on, due,
                        s.name, b.suppliers[s.name]["id"], s.account, round(net, -1), s.vat,
                        due if due <= b.last_day else None)
            b.bills.append(bill)

        # Payroll on payday: wages out net of tax, the tax and AGA owed to the
        # state until the term, holiday pay earned for next June.
        pay_on = workdays.backward(_on(y, m, spec.payday))
        if pay_on <= b.last_day:
            cost = level * spec.payroll * rng.uniform(0.97, 1.03)
            gross = cost / (1 + AGA * (1 + HOLIDAY) + HOLIDAY + PENSION)
            ferie = gross * HOLIDAY
            if m == 6:
                # June: no wages withheld for the holiday month; last year's
                # holiday pay goes out instead.
                owed = holiday_owed.get(y - 1, 0.0)
                if owed:
                    b.post(pay_on, [(2940, owed), (1920, -owed)], "Utbetaling feriepenger")
            b.post(pay_on, [(5000, gross), (2600, -gross * WITHHOLDING),
                            (1920, -gross * (1 - WITHHOLDING))], f"Lønn {_mname(m)}")
            b.post(pay_on, [(5020, ferie), (2940, -ferie)], f"Feriepenger {_mname(m)}")
            b.post(pay_on, [(5400, (gross + ferie) * AGA), (2770, -(gross + ferie) * AGA)],
                   f"Arbeidsgiveravgift {_mname(m)}")
            b.post(pay_on, [(5945, gross * PENSION), (1920, -gross * PENSION)], "Pensjon")
            holiday_owed[y] = holiday_owed.get(y, 0.0) + ferie

        # Depreciation and the loan, monthly.
        if last <= b.last_day:
            b.post(last, [(6010, spec.opening_assets * 0.7 / 60), (1230, -spec.opening_assets * 0.7 / 60)],
                   "Avskrivning biler")
            b.post(last, [(6020, spec.opening_assets * 0.3 / 60), (1250, -spec.opening_assets * 0.3 / 60)],
                   "Avskrivning inventar")
        if spec.dividend and m == 5 and _on(y, m, 27) <= b.last_day:
            b.post(workdays.backward(_on(y, m, 27)), [(2050, spec.dividend), (1920, -spec.dividend)],
                   "Utbytte")
        if spec.loan_monthly and _on(y, m, 20) <= b.last_day:
            interest = spec.loan * 0.065 / 12
            b.post(_on(y, m, 20), [(2220, spec.loan_monthly), (8150, interest),
                                   (1920, -(spec.loan_monthly + interest))], "Avdrag og renter")
        y, m = (y + (m == 12), m % 12 + 1)

    # The scripted turns: an invoice left unpaid, a big bill on its way.
    for event in spec.events:
        event(b, rng)

    _book_documents(b)
    _book_terms(b)
    b.postings.sort(key=lambda p: (p.date, p.voucher))
    return b


def _book_documents(b: Books) -> None:
    """Every invoice and bill into the journal, with its payment."""
    for inv in b.invoices:
        b.post(inv.date, [(1500, inv.gross), (3000, -inv.net), (2700, -(inv.gross - inv.net))],
               f"Faktura {inv.number}", customer=inv.customer)
        if inv.paid:
            b.post(inv.paid, [(1920, inv.gross), (1500, -inv.gross)],
                   f"Innbetaling faktura {inv.number}", customer=inv.customer)
    for bill in b.bills:
        lines = [(bill.account, bill.net), (2400, -bill.gross)]
        if bill.vat:
            lines.append((2710, bill.gross - bill.net))
        bill.voucher = b.post(bill.date, lines, f"{bill.supplier} {bill.number}",
                              supplier=bill.supplier)
        if bill.paid:
            b.post(bill.paid, [(2400, bill.gross), (1920, -bill.gross)],
                   f"Betaling {bill.supplier}", supplier=bill.supplier)


def _book_terms(b: Books) -> None:
    """VAT closed into the settlement account at each term's end and paid on
    its due date; withholding and AGA paid on theirs; last year's tax paid in
    February and April."""
    first = date(b.today.year - 1, 1, 1)
    for year in (b.today.year - 1, b.today.year):
        for months, _ in VAT_TERMS:
            end = _on(year, months[1], 31)
            if end > b.last_day:
                continue
            start = date(year, months[0], 1)
            net = sum(p.amount for p in b.postings
                      if p.account in (2700, 2710) and start <= p.date <= end)
            out = sum(p.amount for p in b.postings if p.account == 2700 and start <= p.date <= end)
            b.post(end, [(2700, -out), (2710, -(net - out)), (2740, net)], f"Mva-termin {months[0]}-{months[1]}")
            due = workdays.forward(_due(year, months[0], VAT_TERMS))
            if due <= b.last_day:
                b.post(due, [(2740, -net), (1920, net)], f"Betalt mva {months[0]}-{months[1]}")
        for months, _ in TAX_TERMS:
            end = _on(year, months[1], 31)
            due = workdays.forward(_due(year, months[0], TAX_TERMS))
            if due > b.last_day or end < first:
                continue
            start = date(year, months[0], 1)
            for acct, text in ((2600, "forskuddstrekk"), (2770, "arbeidsgiveravgift")):
                owed = -sum(p.amount for p in b.postings
                            if p.account == acct and start <= p.date <= end and p.amount < 0)
                if owed:
                    b.post(due, [(acct, owed), (1920, -owed)], f"Betalt {text} {months[0]}-{months[1]}")

    # Last year's tax: booked at year end, paid in two halves.
    ye = date(b.today.year - 1, 12, 31)
    profit = -sum(p.amount for p in b.postings if p.account >= 3000 and p.date.year == ye.year)
    if profit > 0:
        tax = round(profit * TAX, -2)
        b.post(ye, [(8300, tax), (2500, -tax)], "Skattekostnad")
        for d in (date(b.today.year, 2, 15), date(b.today.year, 4, 15)):
            d = workdays.forward(d)
            if d <= b.last_day:
                b.post(d, [(2500, tax / 2), (1920, -tax / 2)], "Betalt skatt")


MONTH_NAMES = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
               "august", "september", "oktober", "november", "desember"]


def _mname(m: int) -> str:
    return MONTH_NAMES[m - 1]
