"""Who is late, who always is, and what goes out today (card 20).

`cards.py` raised one card per late customer with a reminder drafted. The card
did not know the customer: one who always pays three weeks late and one who
always pays on the day, now three weeks late, got the same card. They need
the opposite: the first is the forecast's ordinary case, the second is the
warning sign — a dispute, a lost invoice, or money trouble — and wants a phone
call before a reminder.

So each late customer is measured against his own habit (`payment_habits`):

- **uvanlig** — he usually pays inside the company's reminder rule, or he is
  now more than HABIT_FACTOR times his own usual lateness. Ring first.
- **fast** — his habit is past the rule, over at least MIN_CUSTOMER paid
  invoices. A reminder, and the forecast already expects the money late.
- **ny** — too few paid invoices to know.

And each has a step on a ladder: a reminder, a second firmer one FOLLOW_UP_DAYS
after it, and then the owner's own decision. After REMINDERS reminders without
payment the next step (a debt-collection warning, a call, an instalment
agreement) has consequences, and is his: nothing is drafted for it.

The step is read off the deck: a "Send påminnelsen" approved on the customer's
card, not yet released, is a reminder sent in this round of lateness. When he
pays, `cards.reconcile` releases the card, and the next time he is late starts
at the first step again.
"""
from datetime import date, timedelta

import config
import workdays

REMINDERS = 2             # after this many, the next step is the owner's
HABIT_FACTOR = 2          # this far past his own usual lateness is unusual even for him
DEADLINE_DAYS = 7         # the new deadline a reminder gives
WAIT_DAYS = 14            # as cards.FOLLOW_UP_DAYS: the answer a reminder gets
SEND = "send"


def habit(name: str, worst: int, habits: dict | None, late_days: int) -> dict:
    """The customer's habit, and what this lateness is against it."""
    own = ((habits or {}).get("customers") or {}).get(name)
    if not own:
        return {"kind": "ny", "days": None, "invoices": 0}
    days, n = own["days"], own["invoices"]
    if days < late_days or worst > HABIT_FACTOR * max(days, 1):
        kind = "uvanlig"
    else:
        kind = "fast"
    return {"kind": kind, "days": days, "invoices": n}


def sent(history: list[dict], key: str) -> list[str]:
    """The days a reminder went out in this round of lateness, oldest first."""
    return sorted(c.get("closed") or "" for c in history
                  if c.get("key") == key and c.get("status") == "done"
                  and not c.get("released")
                  and (c.get("decided") or {}).get("option") == SEND)


def step(dates: list[str]) -> int:
    """1: the first reminder, 2: the second, 3: the owner's decision."""
    return min(len(dates), REMINDERS) + 1


def deadline(today: date) -> date:
    return workdays.forward(today + timedelta(days=DEADLINE_DAYS))


def _no(d: date | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return d.strftime("%d.%m.%Y")


def _kr(v: float) -> str:
    return f"{round(v):,}".replace(",", " ")


def _pay_to(account: str | None) -> str:
    return (f"til konto {account}" if account
            else "til kontonummeret som står på fakturaen")


def draft(items: list[dict], total: float, n: int, today: date,
          last_sent: str | None = None, account: str | None = None) -> dict | None:
    """The reminder for step `n`; none for the owner's step."""
    if n > REMINDERS:
        return None
    lines = "\n".join(
        f"- Faktura {i.get('number') or '—'}, forfalt {_no(i['due'])}, "
        f"{_kr(i['amount'])} kr" for i in items)
    pay = (f"Til sammen {_kr(total)} kr. Vi ber om at beløpet betales innen "
           f"{_no(deadline(today))} {_pay_to(account)}, merket med fakturanummeret.")
    to = next((i.get("email") for i in items if i.get("email")), "")
    name = config.COMPANY_NAME
    if n == 1:
        return {
            "kind": "e-post", "to": to,
            "subject": f"Påminnelse – forfalte fakturaer fra {name}",
            "text": (
                f"Hei,\n\nVi ser at følgende fakturaer står som ubetalte hos oss:\n\n"
                f"{lines}\n\n{pay}\n\n"
                f"Er det noe som er uklart, eller har det skjedd noe med "
                f"faktureringen, så si fra.\n\nVennlig hilsen\n{name}")}
    since = f" {_no(last_sent)}" if last_sent else ""
    return {
        "kind": "e-post", "to": to,
        "subject": f"Ny påminnelse – forfalte fakturaer fra {name}",
        "text": (
            f"Hei,\n\nVi sendte en påminnelse{since} om fakturaene under, og har "
            f"ikke sett betaling:\n\n{lines}\n\n{pay}\n\n"
            f"Har dere innsigelser til kravet, eller trenger dere en avtale om "
            f"nedbetaling, ta kontakt så snart som mulig. Uten betaling eller "
            f"svar innen fristen må vi vurdere videre tiltak.\n\n"
            f"Vennlig hilsen\n{name}")}


def habit_text(h: dict, worst: int) -> str:
    """One sentence on the customer's habit, for the card."""
    if h["kind"] == "ny":
        return ""
    usual = (f"vanligvis {h['days']} dager etter forfall" if h["days"] > 0
             else "vanligvis innen forfall")
    basis = f"{h['invoices']} betalte fakturaer"
    if h["kind"] == "fast":
        return (f"De betaler fast sent: {usual} ({basis}), og prognosen regner "
                f"allerede med det. Vurder kortere betalingsfrist eller "
                f"purregebyr for dem.")
    return (f"Det er uvanlig for dem: de betaler {usual} ({basis}), nå er det "
            f"{worst}. Ring og hør om noe er galt — en tvist, en faktura som "
            f"ikke kom fram, eller pengemangel.")


ACTIONS = {"ring": "Ring dem", 1: "Send påminnelse", 2: "Send ny påminnelse",
           3: "Din beslutning"}


def today_list(late: list[dict], history: list[dict], today: date) -> dict:
    """Every late customer, with what to do about him today.

    `late` is what `cards._late` found: customer, amount, worst, habit, step
    and key. Each row is matched to the customer's live card: an open one is
    something to do today, a snoozed one waits for its day, and one approved
    in the last WAIT_DAYS waits for the customer's answer."""
    rows = []
    for c in late:
        cards = [k for k in history if k.get("key") == c["key"]]
        live = next((k for k in cards if k.get("status") in ("open", "snoozed")), None)
        held = max((k for k in cards if k.get("status") == "done" and not k.get("released")),
                   key=lambda k: k.get("closed") or "", default=None)
        row = {"customer": c["customer"], "amount": round(c["amount"], 2),
               "late": c["worst"], "habit": c["habit"]["kind"],
               "habit_days": c["habit"]["days"], "step": c["step"],
               "card": None, "today": False, "action": "", "until": None}
        if live and live.get("status") == "open":
            ring = c["habit"]["kind"] == "uvanlig" and c["step"] < 3
            row.update(card=live["id"], today=True,
                       action=ACTIONS["ring" if ring else c["step"]])
        elif live:
            row.update(card=live["id"], action="Utsatt", until=live.get("snooze_until"))
        elif held:
            closed = date.fromisoformat(held.get("closed") or today.isoformat())
            option = (held.get("decided") or {}).get("option")
            row.update(action={SEND: "Venter på betaling", "call": "Du ringer dem",
                               "inkasso": "Du sender inkassovarsel"}.get(option, "Tatt hånd om"),
                       until=(closed + timedelta(days=WAIT_DAYS)).isoformat())
        else:
            continue
        rows.append(row)
    order = {3: 0, "uvanlig": 1}
    rows.sort(key=lambda r: (not r["today"], order.get(r["step"], order.get(r["habit"], 2)),
                             -r["amount"]))
    return {"rows": rows, "today": sum(r["today"] for r in rows),
            "total": round(sum(r["amount"] for r in rows), 2)}
