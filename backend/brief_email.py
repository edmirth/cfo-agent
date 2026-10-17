"""The Monday brief, as the email the CEO reads on the phone.

Complete on its own: the app runs on a Mac nobody's phone can reach, so a
"read more" link would lead nowhere. Everything the brief says is in the
email — the light, the low point, what changed, the decisions spelled out,
the books and the record. One narrow column, inline styles, nothing to load:
mail apps strip stylesheets and block images, and a brief that needs either
is a brief that reads wrong.

**The stored brief, never a fresh one.** What goes out is the brief kept in
`reports` for this week, exactly as the web app shows it. Sending writes
nothing new and calls no model, so a retried send costs nothing and says
what the first attempt would have said.

**Once a week, unless asked.** A scheduled send skips a brief already sent.
Sending by hand always sends: that is someone asking to see it.
"""
import html
import logging
import uuid
from datetime import date

import brief
import company
import db
import job_runs
import mailer

log = logging.getLogger("cfo.brief_email")

COLOURS = {"green": "#059669", "yellow": "#d97706", "red": "#dc2626"}
INK, MUTED, RULE = "#111827", "#6b7280", "#e5e7eb"
FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,"
        "sans-serif")


class NotWritten(RuntimeError):
    """There is no brief for this week to send."""


def subject(b: dict) -> str:
    week = b["period"].split("-W")[1].lstrip("0")
    return f"Mandagsbrevet uke {week}: {brief.LIGHTS[b['light']]}"


def text(b: dict) -> str:
    return (f"{b['body']}\n\n—\nMandagsbrevet fra Arvaka, skrevet "
            f"{brief._day(b['made_on'])}. Tallene er hentet fra Tripletex.")


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _section(title: str, body: str) -> str:
    return (f'<tr><td style="padding:18px 0 0">'
            f'<div style="font:600 11px/1.4 {FONT};letter-spacing:.08em;'
            f'text-transform:uppercase;color:{MUTED};margin:0 0 6px">{_e(title)}</div>'
            f'{body}</td></tr>')


def _list(items: list[str]) -> str:
    rows = "".join(f'<li style="margin:0 0 4px">{item}</li>' for item in items)
    return (f'<ul style="margin:0;padding:0 0 0 18px;font:15px/1.5 {FONT};'
            f'color:{INK}">{rows}</ul>')


def _p(s: str, size: int = 15, color: str = INK) -> str:
    return f'<p style="margin:0;font:{size}px/1.5 {FONT};color:{color}">{s}</p>'


def render_html(b: dict) -> str:
    colour = COLOURS[b["light"]]
    week = b["period"].split("-W")[1].lstrip("0")
    d = b["decisions"]

    changed = (_list([_e(c) for c in b["changed"]]) if b["changed"]
               else _p("Ingen endringer verdt å nevne.", color=MUTED))
    if d["count"]:
        items = []
        for c in d["top"]:
            amount = c.get("amount")
            said = amount and brief._kr(amount) in c["title"]
            tail = (f' <span style="color:{MUTED}">· {_e(brief._kr(amount))} kr</span>'
                    if amount and not said else "")
            items.append(f"{_e(c['title'])}{tail}")
        if d["more"]:
            items.append(f'<span style="color:{MUTED}">og {d["more"]} til i appen, '
                         f'under Saker</span>')
        decisions = _list(items)
        decisions_title = f"Trenger deg ({d['count']})"
    else:
        decisions = _p("Ingenting trenger deg denne uka.")
        decisions_title = "Trenger deg"
    books = _p(_e(b["books"]["text"]), 13, MUTED)
    if b["books"]["lines"]:
        books += _list([f'<span style="font-size:13px;color:{MUTED}">{_e(x)}</span>'
                        for x in b["books"]["lines"]])

    return f"""<!doctype html>
<html lang="nb"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(subject(b))}</title></head>
<body style="margin:0;padding:0;background:#f3f4f6">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6">
<tr><td align="center" style="padding:16px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
 style="max-width:560px;background:#ffffff;border-radius:12px;border-left:6px solid {colour}">
<tr><td style="padding:22px 22px 24px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td>
<div style="font:600 11px/1.4 {FONT};letter-spacing:.08em;text-transform:uppercase;color:{MUTED}">
Mandagsbrevet · uke {_e(week)}</div>
<div style="margin:10px 0 0;font:700 13px/1 {FONT};letter-spacing:.08em;color:{colour}">
&#9679; {_e(brief.LIGHTS[b['light']])}</div>
<p style="margin:8px 0 0;font:600 18px/1.4 {FONT};color:{INK}">{_e(b['sentence'])}</p>
<p style="margin:8px 0 0;font:14px/1.5 {FONT};color:{MUTED}">{_e(b['low_point']['text'])}</p>
</td></tr>
{_section("Endret siden forrige mandag", changed)}
{_section(decisions_title, decisions)}
<tr><td style="padding:18px 0 0"><div style="border-top:1px solid {RULE};padding-top:12px">
{books}
<div style="height:6px"></div>
{_p(_e(b['accuracy']['text']), 13, MUTED)}
</div></td></tr>
</table></td></tr></table>
<p style="margin:12px 0 0;font:12px/1.5 {FONT};color:{MUTED}">
Skrevet av Arvaka {_e(brief._day(b['made_on']))}, fra tallene i Tripletex.</p>
</td></tr></table></body></html>"""


def _mark_sent(report_id: int, to: list[str], mail_id: str) -> None:
    with db.tx() as conn:
        row = conn.execute("SELECT facts FROM reports WHERE id = ?",
                           (report_id,)).fetchone()
        facts = db.loads(row["facts"], {}) if row else {}
        facts["sent"] = {"at": db.now(), "to": to, "id": mail_id}
        conn.execute("UPDATE reports SET status = 'sent', facts = ? WHERE id = ?",
                     (db.dumps(facts), report_id))


async def send(today: date | None = None, force: bool | None = None) -> dict:
    """Email this week's brief to the rulebook's recipients.

    `force` sends even when this week's brief has gone already; by default
    it does whenever a person asked, and never when the schedule did.
    """
    today = today or date.today()
    if force is None:
        force = job_runs.trigger.get() == "user"
    b = brief.latest(today)
    if not b or not b["current"]:
        raise NotWritten("Mandagsbrevet for denne uka er ikke skrevet, så det er "
                         "ingenting å sende ennå.")
    if b["status"] == "sent" and not force:
        return {"skipped": True, "period": b["period"], "sent": b.get("sent")}
    to = company.recipients()
    # Per brief and per attempt by hand: a scheduled retry of the same brief
    # carries the same key and is never delivered twice; a send someone asked
    # for is a new email.
    key = f"weekly-brief-{b['id']}" + (f"-{uuid.uuid4().hex}" if force else "")
    mail_id = await mailer.send(to, subject(b), render_html(b), text(b), key)
    _mark_sent(b["id"], to, mail_id)
    return {"skipped": False, "period": b["period"], "to": to, "id": mail_id}
