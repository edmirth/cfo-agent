"""Tripletex, as far as Arvaka asks it, answered from a demo company's books.

Each answer has the shape the real tool gives (field names, signs, columns),
because the modules that read them were written against the real thing and
run here unchanged. Only what the backend and the chat use is answered; any
other tool is refused the way Tripletex refuses one it does not have.
"""
import json
import logging
from datetime import date, timedelta

import workdays
from demo import books as bk

log = logging.getLogger("cfo.demo")

MONTHS = ["Jan", "Feb", "Mars", "April", "Mai", "Juni",
          "Juli", "Aug", "Sept", "Okt", "Nov", "Des"]


class DemoRefused(RuntimeError):
    """What the real client raises as McpError: a call Tripletex refused."""


def _d(s) -> date:
    return date.fromisoformat(str(s)[:10])


def _report(name: str, start: str, end: str, header: str, columns: list[str], rows: list[dict]) -> dict:
    return {
        "request": {"report": {"id": 0, "name": name},
                    "global_filter": {"period": {"type": 0, "start": start, "end": end}},
                    "row_filters": {}},
        "url": None, "report_details": None, "notes": [], "row_limits": [],
        "data_contract": None,
        "table": {"row_header": header,
                  "columns": [{"name": c, "description": None, "percent": False,
                               "type": "NUMBER", "decimals": [2, 2]} for c in columns],
                  "rows": rows, "totals": [], "row_count": len(rows), "omitted_row_count": 0},
        "truncation": None, "png_url": None, "sanity_note": None, "error": None,
        "generatedAt": date.today().isoformat(),
    }


class FakeTripletex:
    def __init__(self, spec):
        self.spec = spec
        self._books = None

    @property
    def b(self) -> bk.Books:
        # Built on first use, so importing the client costs nothing, and once
        # per day, so a demo left running overnight moves with the calendar.
        if self._books is None or self._books.today != date.today():
            self._books = bk.generate(self.spec)
        return self._books

    # ------------------------------------------------------------ plumbing
    async def list_tools(self) -> list[dict]:
        return [{"name": t["name"], "description": t["description"],
                 "inputSchema": t["input_schema"]} for t in AGENT_TOOLS]

    async def call(self, tool: str, arguments: dict | None = None) -> dict:
        args = arguments or {}
        handler = getattr(self, f"_t_{tool}", None)
        if handler is None:
            raise DemoRefused(f"{tool}: Tool {tool} not found")
        return handler(args)

    # ------------------------------------------------------------- ledger
    def _sum(self, lo: int, hi: int, start: date, end_excl: date) -> float:
        b = self.b
        return sum(b._upto(n, end_excl) - b._upto(n, start) for n in bk.ACCOUNTS if lo <= n <= hi)

    def _t_get_balance_sheet(self, a: dict) -> dict:
        start, end = _d(a["dateFrom"]), _d(a["dateToExclusive"])
        lo = int(str(a.get("accountNumberFrom") or 0) or 0)
        hi = int(str(a.get("accountNumberTo") or 9999) or 9999)
        show_all = bool(a.get("showAccountsWithoutTransactionsInPeriod"))
        rows = []
        for i, (n, name) in enumerate(sorted(bk.ACCOUNTS.items())):
            if not lo <= n <= hi:
                continue
            ib = self.b.balance(n, start)
            ub = self.b.balance(n, end, year=start.year)
            moved = self.b.moved(n, start, end)
            if not show_all and not moved and abs(ib) < 0.005 and abs(ub) < 0.005:
                continue
            rows.append({"path": [f"{n} {name}"], "depth": 0, "leaf": True,
                         "cells": [ib, round(ub - ib, 2), ub],
                         "account": {"accountNumber": n, "accountName": name,
                                     "hasPostingsInPeriod": moved, "index": i}})
        return {"request": {}, "generatedAt": date.today().isoformat(), "url": None,
                "table": {"row_header": "Konto",
                          "columns": [{"name": c, "type": "NUMBER", "decimals": [2, 2], "percent": False}
                                      for c in ("Inngående balanse", "Endring", "Utgående balanse")],
                          "rows": rows, "totals": [], "row_count": len(rows),
                          "omitted_row_count": 0}}

    def _t_search_ledger_postings(self, a: dict) -> dict:
        start = _d(a.get("dateFrom") or "2000-01-01")
        end = _d(a.get("dateTo") or "2100-01-01")
        lo, hi = int(a.get("accountNumberFrom") or 0), int(a.get("accountNumberTo") or 9999)
        frm, count = int(a.get("from") or 0), int(a.get("count") or 100)
        hits = [p for p in self.b.postings if lo <= p.account <= hi and start <= p.date < end]
        page = hits[frm:frm + count]
        return {"postings": [{
            "id": p.id, "date": p.date.isoformat(), "description": p.text,
            "accountNumber": p.account, "accountName": bk.ACCOUNTS[p.account],
            "currency": "NOK", "amount": p.amount, "amountCurrency": p.amount,
            "amountGross": p.amount, "amountGrossCurrency": p.amount,
            "vatCode": "0", "vatPercentage": 0,
            "supplierId": None, "supplierName": p.supplier,
            "customerId": None, "customerName": p.customer,
            "projectId": None, "projectName": None, "departmentId": None,
            "departmentName": None, "voucherId": p.voucher, "voucherNumber": p.voucher,
            "type": None} for p in page],
            "from": frm, "count": len(page), "hasMore": frm + count < len(hits)}

    def _t_search_accounting_years(self, a: dict) -> dict:
        y = self.b.today.year
        return {"years": [{"id": 9000 + i, "year": yy, "start": f"{yy}-01-01", "end": f"{yy}-12-31"}
                          for i, yy in enumerate((y - 1, y))]}

    # ------------------------------------------------------------- reports
    def _t_fetch_report(self, a: dict) -> dict:
        name = a.get("report_name")
        start = a.get("period_start") or f"{self.b.today.year}-01-01"
        end = a.get("period_end") or self.b.last_day.isoformat()
        s, e = _d(start), _d(end) + timedelta(days=1)
        builders = {
            "Resultatrapport": self._pnl,
            "Nøkkeltallsrapport": self._ratios,
            "Kundereskontro": self._customer_ledger,
            "Leverandørreskontro": self._supplier_ledger,
            "Topp 20 kunder": self._top_customers,
        }
        if name == "Saldobalanse per måned":
            raise DemoRefused('fetch_report: the "Saldobalanse per måned" report was removed')
        if name not in builders:
            raise DemoRefused(f"fetch_report: rapporten «{name}» finnes ikke i demoen")
        return builders[name](start, end, s, e)

    def _budget(self, lo: int, hi: int, s: date, e: date) -> float:
        """The budget for a span of P&L accounts, as Tripletex's Budsjett
        column shows it: revenue and payroll planned, the rest at actual."""
        actual = self._presented(lo, hi, s, e)
        spec = self.spec
        if 3000 <= lo and hi <= 3999:
            return round(actual * spec.budget_revenue, 2)
        if 5000 <= lo and hi <= 5999 and spec.budget_payroll:
            revenue = self._presented(3000, 3999, s, e) * spec.budget_revenue
            share = (hi - lo + 1) / 1000 if (lo, hi) != (5000, 5999) else 1
            return round(revenue * spec.budget_payroll * share, 2)
        return actual

    def _presented(self, lo: int, hi: int, s: date, e: date) -> float:
        """Revenue and income shown positive, costs positive, as the report does."""
        v = self._sum(lo, hi, s, e)
        return round(-v if (3000 <= lo <= 3999 or 8000 <= lo <= 8099) else v, 2)

    def _pnl(self, start, end, s, e) -> dict:
        rows = []

        def row(path, actual, budget, leaf=False):
            rows.append({"depth": path.count(" > "), "path": path, "leaf": leaf,
                         "cells": [round(actual, 2), round(budget, 2), round(actual - budget, 2)]})

        def group(path, lo, hi):
            act, bud = self._presented(lo, hi, s, e), self._budget(lo, hi, s, e)
            row(path, act, bud)
            for n, name in sorted(bk.ACCOUNTS.items()):
                if lo <= n <= hi and self.b.moved(n, s, e):
                    row(f"{path} > {n} {name}", self._presented(n, n, s, e),
                        self._budget(n, n, s, e) if not (5000 <= n <= 5999) else
                        self._budget(5000, 5999, s, e) * (self._presented(n, n, s, e) /
                                                          (self._presented(5000, 5999, s, e) or 1)),
                        leaf=True)
            return act, bud

        inc, inc_b = self._presented(3000, 3999, s, e), self._budget(3000, 3999, s, e)
        cost_groups = [("Varekostnad", 4000, 4999), ("Lønnskostnad", 5000, 5999),
                       ("Avskrivning på varige driftsmidler og immaterielle eiendeler", 6000, 6099),
                       ("Annen driftskostnad", 6100, 7999)]
        costs = [(n, self._presented(lo, hi, s, e), self._budget(lo, hi, s, e)) for n, lo, hi in cost_groups]
        cost, cost_b = sum(c for _, c, _ in costs), sum(c for _, _, c in costs)
        row("Driftsresultat", inc - cost, inc_b - cost_b)
        row("Driftsresultat > Driftsinntekter", inc, inc_b)
        group("Driftsresultat > Driftsinntekter > Salgsinntekter", 3000, 3699)
        row("Driftsresultat > Driftskostnader", cost, cost_b)
        for (n, lo, hi) in cost_groups:
            group(f"Driftsresultat > Driftskostnader > {n}", lo, hi)
        fin_in, fin_out = self._presented(8000, 8099, s, e), self._presented(8100, 8199, s, e)
        net = fin_in - fin_out
        fp = "Finansinntekter og finanskostnader (netto finansresultat)"
        row(fp, net, net)
        group(f"{fp} > Finansinntekter", 8000, 8099)
        group(f"{fp} > Finanskostnader", 8100, 8199)
        pre = inc - cost + net
        pre_b = inc_b - cost_b + net
        tax = self._presented(8300, 8399, s, e)
        row("Ordinært resultat før skattekostnad", pre, pre_b)
        row("Skattekostnad på ordinært resultat", tax, tax)
        row("Ordinært resultat", pre - tax, pre_b - tax)
        row("Årsresultat", pre - tax, pre_b - tax)
        return _report("Resultatrapport", start, end, "Regnskapskonto",
                       ["Faktisk", "Budsjett", "Avvik"], rows)

    def _position(self, at: date) -> dict:
        """Assets, short-term debt and equity at the start of `at`."""
        bal = lambda lo, hi: sum(self.b.balance(n, at) for n in bk.ACCOUNTS if lo <= n <= hi)
        assets = bal(1000, 1999)
        current = bal(1400, 1999)
        short = -bal(2300, 2999)
        debt = -bal(2100, 2999)
        return {"assets": assets, "current": current, "short": short,
                "debt": debt, "equity": assets - debt}

    def _ratios(self, start, end, s, e) -> dict:
        def figures(s, e):
            inc = self._presented(3000, 3999, s, e)
            op = inc - self._presented(4000, 7999, s, e)
            dep = self._presented(6000, 6099, s, e)
            net = op + self._presented(8000, 8099, s, e) - self._presented(8100, 8199, s, e) \
                - self._presented(8300, 8399, s, e)
            pos = self._position(e)
            pct = lambda a, b: round(a / b * 100, 2) if b else None
            return {"EBITDA": op + dep,
                    "Likviditetsgrad 1": round(pos["current"] / pos["short"], 2) if pos["short"] else None,
                    "Egenkapitalandel i % (soliditet)": pct(pos["equity"], pos["assets"]),
                    "Gjeldsgrad": round(pos["debt"] / pos["equity"], 2) if pos["equity"] else None,
                    "Overskuddsgrad": pct(op, inc),
                    "Totalrentabilitet i % (lønnsomhet)": pct(op, pos["assets"]),
                    "Rentabilitet av egenkapital": pct(net, pos["equity"])}
        now = figures(s, e)
        before = figures(s.replace(year=s.year - 1), e.replace(year=e.year - 1))
        rows = [{"depth": 0, "path": k, "leaf": True, "percent": "%" in k or k in ("Overskuddsgrad", "Rentabilitet av egenkapital"),
                 "cells": [v, before[k]], "decimals": [2, 2]} for k, v in now.items()]
        return _report("Nøkkeltallsrapport", start, end, "Nøkkeltall",
                       ["Valgt periode", "Samme periode i fjor"], rows)

    def _open_invoices(self, at: date) -> list:
        return [i for i in self.b.invoices if i.date < at and (i.paid is None or i.paid >= at)]

    def _open_bills(self, at: date) -> list:
        return [x for x in self.b.bills if x.date < at and (x.paid is None or x.paid >= at)]

    def _customer_ledger(self, start, end, s, e) -> dict:
        by: dict[str, float] = {}
        for i in self._open_invoices(e):
            by[i.customer] = by.get(i.customer, 0.0) + i.gross
        rows = [{"depth": 0, "path": n, "leaf": True,
                 "cells": [self.b.customers[n]["number"], round(v, 2)]}
                for n, v in sorted(by.items(), key=lambda kv: -kv[1])]
        return _report("Kundereskontro", start, end, "Kundenavn", ["Kundenummer", "Beløp"], rows)

    def _supplier_ledger(self, start, end, s, e) -> dict:
        by: dict[str, float] = {}
        for x in self._open_bills(e):
            by[x.supplier] = by.get(x.supplier, 0.0) - x.gross
        rows = [{"depth": 0, "path": n, "leaf": True,
                 "cells": [self.b.suppliers[n]["number"], round(v, 2)]}
                for n, v in sorted(by.items(), key=lambda kv: kv[1])]
        return _report("Leverandørreskontro", start, end, "Leverandørnavn",
                       ["Leverandørnummer", "Beløp"], rows)

    def _top_customers(self, start, end, s, e) -> dict:
        by: dict[str, float] = {}
        for i in self.b.invoices:
            if s <= i.date < e:
                by[i.customer] = by.get(i.customer, 0.0) + i.net
        total = sum(by.values()) or 1
        rows, acc = [], 0.0
        for n, v in sorted(by.items(), key=lambda kv: -kv[1]):
            acc += v
            rows.append({"depth": 0, "path": n, "leaf": True,
                         "cells": [round(v, 2), round(v / total * 100, 2), round(acc / total * 100, 2)]})
        return _report("Topp 20 kunder", start, end, "Kunde", ["Omsetning", "Andel", "Akkumulert"], rows)

    # ------------------------------------------------------------ documents
    def _t_search_invoices(self, a: dict) -> dict:
        s = _d(a.get("invoiceDateFrom") or "2000-01-01")
        e = _d(a.get("invoiceDateTo") or "2100-01-01")
        frm, count = int(a.get("from") or 0), int(a.get("count") or 100)
        today = self.b.today
        hits = [i for i in self.b.invoices if s <= i.date <= e]
        if a.get("customerId"):
            hits = [i for i in hits if i.customer_id == int(a["customerId"])]
        rows = [{"id": i.id, "invoiceNumber": i.number, "invoiceDate": i.date.isoformat(),
                 "dueDate": i.due.isoformat(), "customerId": i.customer_id,
                 "customerName": i.customer, "customerEmail": "",
                 "amount": i.gross, "amountCurrency": i.gross,
                 "amountOutstanding": i.gross if i.paid is None or i.paid >= today else 0,
                 "amountOutstandingTotal": i.gross if i.paid is None or i.paid >= today else 0,
                 "currency": "NOK", "isCredited": False, "kid": "", "comment": "",
                 "invoiceComment": i.comment, "voucherId": 50000 + i.id, "url": ""}
                for i in hits[frm:frm + count]]
        return {"title": "Kundefakturaer", "columns": [], "rows": rows,
                "generatedAt": today.isoformat()}

    def _t_search_supplier_invoices(self, a: dict) -> dict:
        s = _d(a.get("invoiceDateFrom") or "2000-01-01")
        e = _d(a.get("invoiceDateTo") or "2100-01-01")
        ds = _d(a.get("dueDateFrom") or "2000-01-01")
        de = _d(a.get("dueDateTo") or "2100-01-01")
        frm, count = int(a.get("from") or 0), int(a.get("count") or 100)
        today = self.b.today
        hits = [x for x in self.b.bills if s <= x.date <= e and ds <= x.due <= de]
        rows = [{"voucherId": x.voucher, "voucherNumber": x.voucher, "voucherTempNumber": None,
                 "voucherYear": x.date.year, "supplierId": x.supplier_id,
                 "supplierName": x.supplier, "invoiceNumber": x.number,
                 "invoiceDate": x.date.isoformat(), "dueDate": x.due.isoformat(),
                 "amountCurrency": x.gross, "currencyId": 1, "isCreditNote": False,
                 "lifecycle": "IN_LEDGER", "lifecycleLabel": "Bokført", "source": "legacy",
                 "invoiceId": x.id, "supplierVoucherType": "Leverandørfaktura",
                 "currency": "NOK",
                 "outstandingAmount": x.gross if x.paid is None or x.paid >= today else 0,
                 "kid": "", "url": ""} for x in hits[frm:frm + count]]
        return {"rows": rows, "count": len(rows), "total": len(hits),
                "hasMore": frm + count < len(hits), "newFlowSearched": False,
                "sources": {"new_flow": 0, "legacy": len(rows)}, "appliedFilters": [],
                "attestationAvailable": False}

    def _t_search_customers(self, a: dict) -> dict:
        frm, count = int(a.get("from") or 0), int(a.get("count") or 100)
        items = [] if a.get("isInactive") else list(self.b.customers.items())
        page = items[frm:frm + count]
        return {"customers": [{"id": c["id"], "name": n, "email": "", "invoiceEmail": "",
                               "organizationNumber": c["org"], "isSupplier": False,
                               "isInactive": False, "isPrivateIndividual": not c["org"],
                               "url": ""} for n, c in page],
                "hasMore": frm + count < len(items), "from": frm,
                "nextFrom": frm + count, "fullResultSize": len(items)}

    # --------------------------------------------------------- the backlog
    def _t_get_voucher_inbox_count(self, a: dict) -> dict:
        return {"count": self.spec.inbox, "url": ""}

    def _t_list_pending_attestations(self, a: dict) -> dict:
        return {"rows": [], "count": 0, "hasMore": False, "from": int(a.get("from") or 0),
                "scope": a.get("scope") or "mine", "accessHint": ""}

    def _t_get_supplier_invoices_for_approval(self, a: dict) -> dict:
        return {"invoices": []}

    # ----------------------------------------------------------------- bank
    def _t_get_bank_reconciliation_periods(self, a: dict) -> dict:
        s, e = _d(a["dateFrom"]), _d(a["dateTo"])
        periods, m = [], date(s.year, s.month, 1)
        this_month = date(self.b.today.year, self.b.today.month, 1)
        while m <= min(e, self.b.last_day):
            nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
            periods.append({"accountNumber": "1920",
                            "period": {"id": m.year * 100 + m.month, "start": m.isoformat(),
                                       "end": (nxt - timedelta(days=1)).isoformat()},
                            "status": "open" if m >= this_month else "closed",
                            "url": "", "difference": 0})
            m = nxt
        return {"range": {"from": s.isoformat(), "to": e.isoformat()},
                "accounts": [{"id": 1, "number": "1920", "name": "Bedriftskonto",
                              "currency": "NOK", "requireReconciliation": True}],
                "periods": periods}

    def _t_get_unmatched_bank_transactions(self, a: dict) -> dict:
        start = _d(a["date"])
        nxt = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        moved = [p for p in self.b.postings if p.account == 1920 and start <= p.date < nxt]
        if a.get("matchStatus") == "matched":
            # The feed reaches the last working day, as a current one does.
            reach = workdays.backward(self.b.last_day)
            return {"matched": [{"postedDate": p.date.isoformat()} for p in moved[-20:]]
                    + ([{"postedDate": reach.isoformat()}] if start <= reach < nxt else [])}
        return {"totals": {"matched": {"sum": round(sum(p.amount for p in moved), 2)},
                           "unmatched": {"sum": 0.0, "count": 0, "in": 0.0, "out": 0.0},
                           "awaitingApproval": {"sum": 0.0},
                           "unmatchedPostings": {"sum": 0.0, "count": 0}},
                "unmatched": [], "truncated": False}

    # -------------------------------------------------------------- sandbox
    def _t_tripletex_run_script(self, a: dict) -> dict:
        code = a.get("code") or ""
        if "search_employees" in code and "percentage" in code:
            return {"output": [json.dumps({"headcount": self.spec.headcount,
                                           "with_percentage": self.spec.headcount,
                                           "fte": self.spec.fte})],
                    "executionTimeMs": 40}
        raise DemoRefused("tripletex_run_script: skript kjøres ikke i demoen; "
                          "bruk verktøyene direkte")


# The tools the chat is offered in demo mode, run here against the books. The
# real Tripletex toolset is reached through Anthropic's servers, which cannot
# reach a laptop, so the chat gets these as ordinary tools instead.
def _schema(props: dict, required=()) -> dict:
    return {"type": "object", "properties": props, "required": list(required)}


_DATE = {"type": "string", "description": "yyyy-MM-dd"}
AGENT_TOOLS = [
    {"name": "fetch_report",
     "description": ("Fetch a Tripletex business report as a JSON table. Reports: "
                     "Resultatrapport (P&L with Faktisk, Budsjett, Avvik), Nøkkeltallsrapport "
                     "(key ratios), Kundereskontro (open receivables per customer), "
                     "Leverandørreskontro (open payables per supplier, negative), "
                     "Topp 20 kunder (revenue per customer). Revenue and costs are shown "
                     "positive in Resultatrapport."),
     "input_schema": _schema({"report_name": {"type": "string", "enum": [
         "Resultatrapport", "Nøkkeltallsrapport", "Kundereskontro",
         "Leverandørreskontro", "Topp 20 kunder"]},
         "period_start": _DATE, "period_end": _DATE}, ["report_name", "period_start", "period_end"])},
    {"name": "get_balance_sheet",
     "description": ("Trial balance (saldobalanse) for a period: one row per account with "
                     "Inngående balanse, Endring and Utgående balanse, ledger signs (debit "
                     "positive, credit negative). Result accounts restart each 1 January."),
     "input_schema": _schema({"dateFrom": _DATE, "dateToExclusive": _DATE,
                              "accountNumberFrom": {"type": "integer"},
                              "accountNumberTo": {"type": "integer"},
                              "showAccountsWithoutTransactionsInPeriod": {"type": "boolean"}},
                             ["dateFrom", "dateToExclusive"])},
    {"name": "search_invoices",
     "description": ("Customer invoices by invoice date: number, dates, customer, amount incl. "
                     "VAT, amountOutstanding (0 when paid)."),
     "input_schema": _schema({"invoiceDateFrom": _DATE, "invoiceDateTo": _DATE,
                              "customerId": {"type": "integer"},
                              "from": {"type": "integer"}, "count": {"type": "integer"}},
                             ["invoiceDateFrom", "invoiceDateTo"])},
    {"name": "search_supplier_invoices",
     "description": ("Supplier invoices by invoice or due date: supplier, dates, amount, "
                     "outstandingAmount (0 when paid)."),
     "input_schema": _schema({"invoiceDateFrom": _DATE, "invoiceDateTo": _DATE,
                              "dueDateFrom": _DATE, "dueDateTo": _DATE,
                              "from": {"type": "integer"}, "count": {"type": "integer"}})},
    {"name": "search_customers",
     "description": "The company's customers with id, name and organisation number.",
     "input_schema": _schema({"from": {"type": "integer"}, "count": {"type": "integer"}})},
    {"name": "search_ledger_postings",
     "description": ("Ledger postings (hovedbok) for an account range and dates, newest "
                     "last. dateTo is exclusive."),
     "input_schema": _schema({"dateFrom": _DATE, "dateTo": _DATE,
                              "accountNumberFrom": {"type": "integer"},
                              "accountNumberTo": {"type": "integer"},
                              "from": {"type": "integer"}, "count": {"type": "integer"}},
                             ["dateFrom", "dateTo"])},
    {"name": "get_voucher_inbox_count",
     "description": "How many vouchers wait unposted in the voucher inbox (bilagsmottak).",
     "input_schema": _schema({})},
    {"name": "list_pending_attestations",
     "description": "Vouchers waiting for approval (attestering).",
     "input_schema": _schema({"scope": {"type": "string", "enum": ["mine", "all"]}})},
    {"name": "search_accounting_years",
     "description": "The company's accounting years with first and last day.",
     "input_schema": _schema({"yearFrom": {"type": "integer"}, "yearTo": {"type": "integer"}})},
]
AGENT_TOOL_NAMES = frozenset(t["name"] for t in AGENT_TOOLS)
