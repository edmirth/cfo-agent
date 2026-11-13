"""Bucket the flows into weeks and walk both lines down."""
from datetime import date, timedelta

import commitments

from .common import LATE_SPREAD_WEEKS, MONTH_NAMES, MVA_RATE, PAY_LAG_DAYS, WEEKS
from .payroll import _ferie_withheld
from .narrative import after_text


# The money in that is kept when it lands after the window: customer invoices
# sent, and the invoicing sent inside the window. Not the slow and doubtful
# spreads, which are ours, nor the accounts' fallback, which has no invoice.
AFTER_KINDS = {"ar", "recurring", "recurring_usual", "new_sales"}


def _bank_payload(booked: float, gap: dict | None, ar_paid: list,
                  ap_paid: list) -> dict:
    """How the opening balance was arrived at, for the declaration."""
    if not gap:
        return {"booked": round(booked, 2), "adjustment": None, "known": False}
    return {
        "booked": round(booked, 2),
        "adjustment": gap["adjustment"],
        "known": not gap["unknown"],
        "lines": gap["lines"], "in": gap["in"], "out": gap["out"],
        "postings": gap["postings"], "postings_sum": gap["postings_sum"],
        "latest": gap["latest"],
        "stale": gap.get("stale", False),
        "booked_latest": gap.get("booked_latest"),
        "booked_undated": gap.get("booked_undated", 0),
        "accounts": gap["accounts"],
        "unknown": gap["unknown"],
        "approximate": gap["approximate"],
        "settled_ar": round(sum(p["amount"] for p in ar_paid), 2),
        "settled_ar_count": len({(p["name"], p["number"]) for p in ar_paid}),
        "settled_ap": round(sum(p["amount"] for p in ap_paid), 2),
        "settled_ap_count": len({(p["name"], p["number"]) for p in ap_paid}),
    }


def _after_payload(after: dict, week0: date) -> dict | None:
    """The money in after week 13, summed and dated in weeks."""
    if round(after["in"] + after["expected_in"]) <= 0:
        return None
    first, last = (date.fromisoformat(after[k]) for k in ("first", "last"))
    after["items"].sort(key=lambda x: (x["date"], -x["amount"]))
    out = {"in": round(after["in"], 2), "expected_in": round(after["expected_in"], 2),
           "first": after["first"], "last": after["last"],
           "first_week": first.isocalendar().week, "last_week": last.isocalendar().week,
           "start": (week0 + timedelta(weeks=WEEKS)).isoformat(),
           "items": after["items"]}
    out["text"] = after_text(out)
    return out


def _assemble(today, week0, opening, committed, expected, rates, credit_days,
              warnings, ar_open, ap_open, vat_share=0.0,
              vat_measured=False, booked_vat=0.0, invoiced=0.0,
              payroll_months=()) -> dict:
    """Bucket the flows into weeks and walk the balance down both lines."""
    weeks = _empty_weeks(week0)
    # Money coming in after the window from invoices sent, or to be sent,
    # inside it (card 17). Without it the last weeks carry the wages and the
    # VAT the invoicing pays for, but not the invoicing, and read as a fall.
    # Only money in: what goes out after the window is not calculated, so
    # this is never netted against the weeks. Next week's window has it.
    after = {"in": 0.0, "expected_in": 0.0, "first": None, "last": None, "items": []}
    _place(committed, "committed", weeks, week0, after)
    _place(expected, "expected", weeks, week0, after)
    _walk(weeks, opening)
    return {
        "as_of": today.isoformat(),
        "opening": round(opening, 2),
        "weeks": weeks,
        "after": _after_payload(after, week0),
        **_low_points(weeks),
        "open_invoices": {"receivable": len(ar_open), "payable": len(ap_open),
                          "receivable_total": round(sum(i["amount"] for i in ar_open), 2),
                          "payable_total": round(sum(i["amount"] for i in ap_open), 2)},
        "assumptions": _assumptions(rates, credit_days, vat_share, vat_measured,
                                    booked_vat, invoiced, payroll_months),
        "warnings": warnings,
    }


def _empty_weeks(week0: date) -> list[dict]:
    weeks = []
    for i in range(WEEKS):
        start = week0 + timedelta(weeks=i)
        weeks.append({"index": i, "start": start.isoformat(),
                      "end": (start + timedelta(days=6)).isoformat(),
                      "label": f"Uke {start.isocalendar().week}",
                      "in": 0.0, "out": 0.0, "expected_in": 0.0,
                      "expected_out": 0.0, "items": []})
    return weeks


def _place(flows: list, scenario: str, weeks: list, week0: date, after: dict) -> None:
    """Each flow into its week; anything already past into the current one,
    and money in after the window into `after`."""
    pre = "" if scenario == "committed" else "expected_"
    for flow in flows:
        i = max(0, (flow["date"] - week0).days // 7)
        if i >= WEEKS:
            _keep_after(flow, scenario, after)
            continue
        key = pre + ("in" if flow["amount"] >= 0 else "out")
        weeks[i][key] += abs(flow["amount"])
        weeks[i]["items"].append({"label": flow["label"], "kind": flow["kind"],
                                  "amount": round(flow["amount"], 2),
                                  "scenario": scenario})


def _keep_after(flow: dict, scenario: str, after: dict) -> None:
    if flow["amount"] <= 0 or flow.get("kind") not in AFTER_KINDS:
        return
    after["in" if scenario == "committed" else "expected_in"] += flow["amount"]
    day = flow["date"].isoformat()
    after["first"] = min(after["first"] or day, day)
    after["last"] = max(after["last"] or day, day)
    after["items"].append({"label": flow["label"], "kind": flow["kind"],
                           "amount": round(flow["amount"], 2),
                           "date": day, "scenario": scenario})


def _walk(weeks: list, opening: float) -> None:
    """Both balances down the weeks, opening and closing each."""
    c_balance = e_balance = opening
    for w in weeks:
        w["committed_open"] = round(c_balance, 2)
        w["expected_open"] = round(e_balance, 2)
        c_balance += w["in"] - w["out"]
        e_balance += w["in"] - w["out"] + w["expected_in"] - w["expected_out"]
        w["committed_close"] = round(c_balance, 2)
        w["expected_close"] = round(e_balance, 2)
        for k in ("in", "out", "expected_in", "expected_out"):
            w[k] = round(w[k], 2)


def _low_points(weeks: list) -> dict:
    """The low point of each line, and the first week each goes under zero.

    Both lines, because they do not fail together and the floor fails first.
    Reading only the expected line told the owner "kontoen går ikke i minus"
    with the committed line 800 000 kr under water — the one sentence this
    module cannot afford to get wrong, since it is the answer to "will I make
    it". The committed line going dry is a fact about money already agreed;
    the expected line going dry is that plus a forecast failing too."""
    low_c = min(weeks, key=lambda w: w["committed_close"])
    low_e = min(weeks, key=lambda w: w["expected_close"])
    neg_e = next((w for w in weeks if w["expected_close"] < 0), None)
    neg_c = next((w for w in weeks if w["committed_close"] < 0), None)
    return {
        "low_committed": {"label": low_c["label"], "start": low_c["start"],
                          "amount": low_c["committed_close"]},
        "low_expected": {"label": low_e["label"], "start": low_e["start"],
                         "amount": low_e["expected_close"]},
        "goes_negative": ({"label": neg_e["label"], "start": neg_e["start"]}
                          if neg_e else None),
        "goes_negative_committed": ({"label": neg_c["label"], "start": neg_c["start"]}
                                    if neg_c else None),
    }


def _assumptions(rates: dict, credit_days: int, vat_share: float, vat_measured: bool,
                 booked_vat: float, invoiced: float, payroll_months) -> dict:
    """What the weeks rest on, as values: the briefing builds the prose."""
    ferie_withheld, ferie_weeks, ferie_weeks_stated = _ferie_withheld()
    return {
        "credit_days": credit_days,
        "pay_lag_days": PAY_LAG_DAYS,
        "late_spread_weeks": LATE_SPREAD_WEEKS,
        "skattetrekk": ("betales til Skatteetaten samme dag som lønnen, "
                        "så hele bruttolønnen går ut på lønningsdagen"),
        "feriepenger_i_lonnsraten": False,
        # The two months that are not like the other ten.
        "halv_skatt_i_desember": ("nettolønnen i desember er høyere, men "
                                  "trekket går ut samme dag, så beløpet "
                                  "ut av kontoen er det samme bruttoet "
                                  "som en vanlig måned"),
        # Values, not sentences: the briefing builds the prose. A month
        # name with "antatt" glued onto it reads fine in a key-value list
        # and wrecks any sentence it is dropped into.
        "feriepenger_maned": MONTH_NAMES[commitments.ferie_month() - 1],
        "feriepenger_maned_oppgitt": commitments.ferie_month_is_stated(),
        "ferie_uker": ferie_weeks,
        "ferie_uker_oppgitt": ferie_weeks_stated,
        "ferie_lonn_holdt_igjen": round(ferie_withheld, 3),
        # Carried rather than recomputed from the rounded share above —
        # 2/26 of a month's wages is not 7.7 % of them, and a figure in
        # the prose that disagrees with the table costs more trust than
        # both are worth.
        "ferie_lonn_utbetalt": round(
            rates["wages_cash"] * (1 - ferie_withheld), 2),
        # Said out loud because it moves which week is the tight one.
        "working_day_shift": ("statutory dues roll forward to the next "
                              "working day, wages back to the last"),
        # Which it is matters: month end is our guess, the 20th is theirs.
        "pay_day": ("fra company.md" if commitments.payday_is_stated()
                    else "månedsslutt, antatt — ikke oppgitt i company.md"),
        "monthly_revenue": round(rates["revenue"], 2),
        "monthly_wages": round(rates["wages"], 2),
        "monthly_wages_cash": round(rates["wages_cash"], 2),
        "monthly_opex": round(rates["opex"], 2),
        "monthly_aga": round(rates.get("aga", 0.0), 2),
        # The liability side of trading that has not happened yet.
        "mva_sats": MVA_RATE,
        "mva_fradrag_andel": round(vat_share, 3),
        "mva_fradrag_malt": vat_measured,
        # Netted off this month's figure rather than charged on top of it:
        # commitments already dates this to the same deadline.
        "mva_bokfort_denne_maneden": round(booked_vat, 2),
        # Likewise netted off, not added to: these invoices are already in
        # the committed line with due dates of their own.
        "fakturert_denne_maneden": round(invoiced, 2),
        # Which payroll runs are actually inside the window. The notes
        # about December and the holiday month describe what a *run* does,
        # so they are gated on the run, not on the months the thirteen
        # weeks happen to touch — those differ at both edges, and a note
        # describing a withheld salary the table does not contain is worse
        # than no note.
        "lonnskjoringer": list(payroll_months),
    }
