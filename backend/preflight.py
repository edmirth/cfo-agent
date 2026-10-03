"""Does the ledger tie out — and is this month even posted yet?

A controller does not analyse figures they have not tied out. The agent could
not tell the difference: it would compute a wage ratio on a month where payroll
was booked and revenue was not, and present it with a straight face. This runs
before it answers, without a model, and tells it what condition the books are
actually in.

Three kinds of check:

- **Posting stalls** — vouchers in the inbox, supplier invoices awaiting
  approval, a payables account that has not moved in months. Cost that exists
  but is not in the P&L yet.
- **Tie-outs** — the customer and supplier subledgers against their general
  ledger accounts. A break means one of the two is wrong and neither can be
  quoted.
- **Period completeness** — this month's revenue and payroll against the
  trailing average. A month with payroll in and invoicing not yet run makes
  every ratio built on it meaningless, which is the single easiest way for an
  AI CFO to say something confidently false.

Everything here is computed from three report calls. No model, so it is cheap
enough to run before every conversation.
"""
import asyncio
import calendar
import logging
from datetime import date

import freshness
import workdays
from mcp_client import mcp

log = logging.getLogger("cfo.preflight")

CACHE_SECONDS = 600

# Thresholds. These are the pre-flight's own; the materiality layer will take
# them over when it lands.
INBOX_NOTE = 1            # any unbooked voucher is worth a word
INBOX_WARN = 15           # this many is a posting backlog, not a queue
TIE_TOLERANCE = 100.0     # kroner; below this a subledger gap is rounding
STALL_MONTHS = 2          # an AP account frozen this long has stopped posting

# An accrual is allowed to sit still for a while — several are settled
# bimonthly, and a quiet quarter is not a fault. Four months is past any normal
# rhythm. The floor exists because small balances legitimately never move:
# 2990 at -6 112 and 2991 at -10 000 have been unchanged all year and nothing is
# wrong with either. Flagging those would train the owner to ignore the check,
# which costs more than the check is worth.
STALE_MONTHS = 4
STALE_MIN_KR = 50_000
COMPLETE_WARN = 0.50      # month below half the trailing average: not posted
COMPLETE_NOTE = 0.80
# Invoices for a month are often registered in the first days of the next and
# dated back, so a closed month is not judged until this many working days in.
INVOICE_GRACE_WORKDAYS = 5

MONTHS = ["Jan", "Feb", "Mars", "April", "Mai", "Juni",
          "Juli", "Aug", "Sept", "Okt", "Nov", "Des"]

# Worst status wins; this is the order.
RANK = {"ok": 0, "unavailable": 1, "note": 2, "warn": 3}


def _rows(report: dict) -> list[dict]:
    return report.get("table", {}).get("rows", []) or []


def _account(row: dict) -> int | None:
    head = (row.get("path") or "").split(" ", 1)[0]
    return int(head) if head.isdigit() else None


def _numbers(row: dict) -> list[float]:
    return [float(c) for c in (row.get("cells") or []) if isinstance(c, (int, float))]


def _balance(rows: list[dict], account: int) -> float | None:
    """Closing balance of one account — the last column of Saldobalanse."""
    for r in rows:
        if _account(r) == account:
            cells = _numbers(r)
            return cells[-1] if cells else None
    return None


def _monthly(rows: list[dict], columns: list[str], low: int, high: int) -> list[tuple[str, float]]:
    """Per-month movement for an account range. The report is cumulative, so a
    month is the difference from the one before it.

    A blank cell means the account did not move that month, not that it went
    to zero — so each account carries its own last balance forward before the
    column is summed, as `overview._cumulative` does. Summing the raw column
    instead drops every quiet account for a month and books it back the next:
    one blank rent cell turned a 10 000 kr cost month into −2 000, and every
    run-rate and completeness check built on the series with it."""
    band = [r for r in rows if (n := _account(r)) is not None and low <= n <= high]
    if not band:
        return []
    carried = [0.0] * len(band)
    out, prev = [], 0.0
    for i, col in enumerate(columns):
        if col not in MONTHS:
            continue
        for j, r in enumerate(band):
            cells = r.get("cells") or []
            if i < len(cells) and isinstance(cells[i], (int, float)):
                carried[j] = float(cells[i])
        cum = sum(carried)
        out.append((col, cum - prev))
        prev = cum
    return out


def _workdays_into(today: date) -> int:
    """Working days elapsed this month, today included."""
    return sum(1 for d in range(1, today.day + 1)
               if workdays.is_working_day(date(today.year, today.month, d)))


def _completeness(revenue: list, payroll: list, today: date) -> list[dict]:
    """Is the month that should be posted actually posted?

    Two questions, kept apart because they have different owners.

    **The month that just closed** — September, asked in October. Its
    invoicing either went out or it did not, and if it did not that is money
    the CEO can go and fetch: a warning and a card. Judged only after
    INVOICE_GRACE_WORKDAYS, because invoices registered on the 2nd and dated
    the 30th land in September's column a few days late.

    **The month still open.** Comparing it with full months warned from the
    1st for every company that invoices at month end, put a high-urgency card
    on the deck most of every month, and called the books provisional. What
    is actually worth saying about an open month is narrower: payroll is in,
    revenue is not — the shape that makes every ratio on the month wrong. That
    is a note for the agent, never a card, and revenue is held to the share of
    the month that has passed, so steady invoicers mid-month are not flagged.
    """
    out: list[dict] = []
    grace = _workdays_into(today) > INVOICE_GRACE_WORKDAYS

    for cid, label_, series, flip in (
            ("revenue_month", "Omsetning forrige måned", revenue, -1),
            ("payroll_month", "Lønn forrige måned", payroll, 1)):
        if len(series) < 2:
            out.append(_check(cid, label_, "unavailable",
                              "Ingen avsluttet måned å vurdere ennå i år."))
            continue
        name, closed = series[-2][0], series[-2][1] * flip
        prior = [v * flip for _, v in series[-5:-2]]
        average = sum(prior) / len(prior) if prior else 0.0
        if average <= 0:
            out.append(_check(cid, label_, "unavailable",
                              "Ingen sammenlignbare måneder."))
            continue
        share = closed / average
        if not grace:
            out.append(_check(
                cid, label_, "ok",
                f"{name}: {_kr(closed)} kr bokført så langt. Vurderes etter "
                f"{INVOICE_GRACE_WORKDAYS} arbeidsdager inn i ny måned, når "
                f"etterregistrerte bilag har kommet inn."))
            continue
        status = ("warn" if share < COMPLETE_WARN
                  else "note" if share < COMPLETE_NOTE else "ok")
        out.append(_check(
            cid, label_, status,
            f"{name}: {_kr(closed)} kr bokført mot {_kr(average)} kr i snitt "
            f"for de tre foregående månedene ({share * 100:.0f} %).",
            "Måneden er over og ikke ferdig bokført; forholdstall som bygger "
            "på den blir feil." if status == "warn" else ""))

    # The open month: only the payroll-in, revenue-out shape.
    if len(revenue) >= 2 and len(payroll) >= 2:
        def avg(series, flip):
            prior = [v * flip for _, v in series[-4:-1]]
            return sum(prior) / len(prior) if prior else 0.0
        rev_avg, pay_avg = avg(revenue, -1), avg(payroll, 1)
        rev_now, pay_now = revenue[-1][1] * -1, payroll[-1][1]
        elapsed = today.day / calendar.monthrange(today.year, today.month)[1]
        expected = rev_avg * elapsed
        if (rev_avg > 0 and pay_avg > 0 and pay_now >= COMPLETE_NOTE * pay_avg
                and rev_now < COMPLETE_WARN * expected):
            out.append(_check(
                "open_month", "Inneværende måned", "note",
                f"{revenue[-1][0]}: lønnen er bokført ({_kr(pay_now)} kr), men "
                f"bare {_kr(rev_now)} kr i omsetning mot rundt "
                f"{_kr(expected)} kr så langt i en vanlig måned.",
                "Ikke regn forholdstall på denne måneden før faktureringen "
                "er inne."))
    return out


def _kr(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{round(value):,}".replace(",", " ")


def _answered(payload, key: str) -> bool:
    """True when the call actually returned this field.

    An empty payload and a genuine zero look identical once you call .get() on
    them, and reporting a failed call as "nothing to see here" is the one
    result a pre-flight must never produce. Absent means unavailable, not zero.
    """
    return isinstance(payload, dict) and key in payload


def _frozen_months(row: dict, columns: list[str]) -> int:
    """How many month-ends in a row this account has closed on the same figure.

    Pair each cell with its column *before* dropping non-numeric ones: filtering
    first and zipping after would shift every month by one the moment a single
    cell reads #AUTH!, and a moving account would be called frozen.
    """
    raw = row.get("cells") or []
    months = [float(c) for c, col in zip(raw, columns)
              if col in MONTHS and isinstance(c, (int, float))]
    if not months:
        return 0
    frozen = 0
    for value in reversed(months[:-1]):
        if abs(value - months[-1]) < 0.01:
            frozen += 1
        else:
            break
    return frozen


def _tie(gl: float, sub: float) -> float:
    """The gap between a general ledger account and its own subledger.

    Both figures arrive on the account's own side: Kundereskontro comes back
    positive against a debit balance, Leverandørreskontro negative against a
    credit balance. So they subtract directly. Negating the payables subledger —
    on the assumption that it arrives positive — reported a gap of exactly twice
    the balance on books that tied perfectly. Subtracting signed values still
    catches an account sitting on the wrong side, which comparing magnitudes
    would quietly call a match.
    """
    return gl - sub


def _check(cid, label, status, headline, detail="") -> dict:
    return {"id": cid, "label": label, "status": status,
            "headline": headline, "detail": detail}


async def build(today: date | None = None) -> dict:
    today = today or date.today()
    start = f"{today.year}-01-01"
    end = today.isoformat()

    inbox, approvals, balance, ar, ap = await asyncio.gather(
        mcp.call("get_voucher_inbox_count"),
        mcp.call("get_supplier_invoices_for_approval"),
        mcp.call("fetch_report", {"report_name": "Saldobalanse per måned",
                                  "period_start": start, "period_end": end, "limit": 0}),
        mcp.call("fetch_report", {"report_name": "Kundereskontro",
                                  "period_start": start, "period_end": end, "limit": 0}),
        mcp.call("fetch_report", {"report_name": "Leverandørreskontro",
                                  "period_start": start, "period_end": end, "limit": 0}),
        return_exceptions=True,
    )
    for name, r in (("bilagsinnboks", inbox), ("godkjenning", approvals),
                    ("saldobalanse", balance), ("kundereskontro", ar),
                    ("leverandørreskontro", ap)):
        if isinstance(r, Exception):
            log.warning("Preflight: %s feilet: %s", name, r)
    inbox, approvals, balance, ar, ap = [
        (None if isinstance(x, Exception) else x)
        for x in (inbox, approvals, balance, ar, ap)]

    rows = _rows(balance or {})
    columns = [c.get("name") for c in (balance or {}).get("table", {}).get("columns", [])]
    checks: list[dict] = []

    # 1. Vouchers received but not booked: cost that exists and is not in the P&L.
    if not _answered(inbox, "count"):
        checks.append(_check("inbox", "Bilagsinnboks", "unavailable",
                             "Kunne ikke lese bilagsinnboksen."))
    else:
        n = inbox.get("count") or 0
        status = "warn" if n >= INBOX_WARN else "note" if n >= INBOX_NOTE else "ok"
        checks.append(_check(
            "inbox", "Bilagsinnboks", status,
            f"{n} bilag ligger ubokført." if n else "Innboksen er tom.",
            "Kostnad som finnes, men ennå ikke er i regnskapet. Resultatet er "
            "tilsvarende for godt." if n else ""))

    # 2. Supplier invoices held at approval — same money, one step further on.
    if not _answered(approvals, "invoices"):
        checks.append(_check("approval", "Til godkjenning", "unavailable",
                             "Kunne ikke lese fakturaer til godkjenning."))
    else:
        pending = approvals.get("invoices") or []
        total = sum(float(i.get("amount") or 0) for i in pending)
        checks.append(_check(
            "approval", "Til godkjenning",
            "note" if pending else "ok",
            f"{len(pending)} leverandørfaktura(er) venter på godkjenning"
            + (f", {_kr(total)} kr." if total else ".") if pending
            else "Ingen fakturaer venter på godkjenning."))

    # 3. A payables account that has stopped moving, or sits on the wrong side.
    ap_row = next((r for r in rows if _account(r) == 2400), None)
    if ap_row is None:
        checks.append(_check("ap_posting", "Leverandørgjeld 2400", "unavailable",
                             "Fant ikke konto 2400 i saldobalansen."))
    else:
        cells = _numbers(ap_row)
        gl_ap = cells[-1] if cells else 0.0
        # Pair each cell with its column *before* dropping non-numeric ones:
        # filtering first and zipping after would shift every month by one
        # the moment a single cell reads #AUTH!, and the stall check would
        # then compare the wrong months and call a moving account frozen.
        frozen = _frozen_months(ap_row, columns)
        problems = []
        if gl_ap > 0:
            problems.append(f"saldoen er {_kr(gl_ap)} kr i debet, der gjeld skal stå i kredit")
        if frozen >= STALL_MONTHS:
            problems.append(f"den har ikke beveget seg på {frozen} måneder")
        checks.append(_check(
            "ap_posting", "Leverandørgjeld 2400",
            "warn" if problems else "ok",
            ("Konto 2400: " + ", og ".join(problems) + ".") if problems
            else f"Konto 2400 står på {_kr(gl_ap)} kr, normal side og i bevegelse.",
            "Enten er leverandørfakturaer sluttet å bli bokført, eller så er det "
            "en forskuddsbetaling eller en posteringsfeil. Kostnadsbildet kan "
            "ikke leses før dette er avklart." if problems else ""))

    # 4 & 5. Subledgers against their general ledger accounts. A break means one
    # of the two is wrong, and neither figure can be quoted until it is found.
    for cid, label_, account, report in (
            ("ar_tie", "Avstemming kundefordringer", 1500, ar),
            ("ap_tie", "Avstemming leverandørgjeld", 2400, ap)):
        gl = _balance(rows, account)
        if not _answered(report, "table") or gl is None:
            checks.append(_check(cid, label_, "unavailable",
                                 f"Kunne ikke avstemme konto {account}."))
            continue
        sub = sum(float(r["cells"][1]) for r in _rows(report)
                  if len(r.get("cells") or []) > 1
                  and isinstance(r["cells"][1], (int, float)))
        gap = _tie(gl, sub)
        ok = abs(gap) < TIE_TOLERANCE
        checks.append(_check(
            cid, label_, "ok" if ok else "warn",
            f"Konto {account} og reskontroen stemmer ({_kr(abs(gl))} kr)." if ok
            else (f"Konto {account} viser {_kr(gl)} kr, mens reskontroen tilsier "
                  f"{_kr(sub)} kr — {_kr(abs(gap))} kr i differanse."),
            "" if ok else "Én av de to er feil. Ingen av tallene kan siteres "
                          "før differansen er funnet."))

    # 6 & 7. Has the month posted that should have been?
    checks += _completeness(_monthly(rows, columns, 3000, 3999),
                            _monthly(rows, columns, 5000, 5999), today)

    # 8. Accruals that have stopped moving. A year-end accrual that was never
    # reversed keeps being read as a current liability, and it is subtracted
    # from the owner's free cash every day until someone notices. Equity
    # (2000-2099) is excluded: it is supposed to sit still.
    stale = []
    for r in rows:
        account = _account(r)
        if account is None or not 2100 <= account <= 2999:
            continue
        cells = _numbers(r)
        owed = -(cells[-1] if cells else 0.0)
        if owed < STALE_MIN_KR:
            continue
        frozen = _frozen_months(r, columns)
        if frozen >= STALE_MONTHS:
            stale.append((r.get("path", "").strip(), owed, frozen))
    stale.sort(key=lambda t: -t[1])
    if stale:
        worst_name, worst_owed, worst_frozen = stale[0]
        rest = (f" Det samme gjelder {len(stale) - 1} konto til."
                if len(stale) == 2 else
                f" Det samme gjelder {len(stale) - 1} andre kontoer."
                if len(stale) > 2 else "")
        checks.append(_check(
            "stale_accrual", "Periodiseringer som står stille", "warn",
            f"{worst_name} står på {_kr(worst_owed)} kr og har ikke beveget "
            f"seg på {worst_frozen} måneder.{rest}",
            "Beløpet regnes som gjeld som forfaller, og trekkes fra de frie "
            "pengene hver dag. Er dette en periodisering fra årsoppgjøret som "
            "aldri ble reversert, er den frie likviditeten høyere enn den ser "
            "ut — og er den reell, bør den ha en forfallsdato."))
    else:
        checks.append(_check(
            "stale_accrual", "Periodiseringer som står stille", "ok",
            "Ingen periodiseringer har stått stille lenge nok til å uroe."))

    worst = max((RANK.get(c["status"], 0) for c in checks), default=0)
    ties_broken = any(c["status"] == "warn" and c["id"].endswith("_tie") for c in checks)
    condition = ("broken" if ties_broken
                 else "provisional" if worst >= RANK["note"] else "clean")

    return {"as_of": end, "condition": condition, "checks": checks}


_flight = freshness.Cached(build, CACHE_SECONDS)


async def cached() -> dict:
    return await _flight.get()


CONDITION_TEXT = {
    "clean": ("Bøkene er ajour. Ingenting hindrer en vanlig analyse.",
              "Nothing is blocking analysis. Do not pad answers with "
              "reassurance about it — say nothing unless asked."),
    "provisional": ("Tallene er foreløpige.",
                    "Say so before any ratio that depends on an affected "
                    "figure, in one clause, not a paragraph."),
    "broken": ("En avstemming stemmer ikke.",
               "Lead with it when the question touches an affected figure. A "
               "subledger that disagrees with its general ledger account means "
               "one of the two is wrong, and neither can be quoted as fact "
               "until someone finds out which."),
}


def briefing(data: dict | None) -> str:
    """The condition block injected into the system prompt.

    Deliberately not a summary: the agent gets the individual findings, in the
    words it can quote straight back to the CEO in Norwegian.
    """
    if not data or not data.get("checks"):
        return ""
    flagged = [c for c in data["checks"] if c["status"] in ("warn", "note")]
    unknown = [c for c in data["checks"] if c["status"] == "unavailable"]
    condition = data.get("condition", "clean")
    headline, instruction = CONDITION_TEXT.get(condition, CONDITION_TEXT["clean"])

    out = ["## The ledger's condition today\n",
           f"Checked {data.get('as_of')} straight from Tripletex, with no model "
           f"involved. **{headline}** {instruction}\n",
           "You did not work this out and must not re-derive it; it is given. "
           "What you do with it is judgement: a figure the checks below do not "
           "touch is as good as ever, and a clean check is not worth a "
           "sentence.\n"]

    if flagged:
        out.append("**What is wrong right now**\n")
        for c in flagged:
            out.append(f"- *{c['label']}* — {c['headline']}"
                       + (f" {c['detail']}" if c["detail"] else ""))
        out.append("")
    if unknown:
        out.append("**Could not be checked** — treat as unknown, never as "
                   "clean: " + ", ".join(c["label"] for c in unknown) + ".\n")
    if not flagged and not unknown:
        out.append("Every check passed.\n")

    out.append("If the CEO asks about something these findings bear on, the "
               "finding comes first and the figure second. Quote the kroner "
               "amounts above as they stand — they are exact.")
    return "\n".join(out)
