"""The Monday brief, as the email the CEO reads on the phone.

Complete on its own: everything the brief says is in the email — the light,
the low point, what changed, the decisions spelled out, the books and the
record. One narrow column, inline styles, nothing to load: mail apps strip
stylesheets and block images, and a brief that needs either is a brief that
reads wrong.

**In Arvaka's brand, as far as mail goes.** Ivory, ink and one green; the
wordmark is live text, never an image, so it reads the same with images off.
A `<style>` block only adjusts for dark mode and narrow screens where an app
honours it; everything that matters is inline.

**Links where the app can be reached.** With `CFO_APP_URL` set, as on the
host, each decision links to its card, where it is decided, and a button opens
the brief in the app. Without it, as on a laptop no phone can reach, there are
no links: one that leads nowhere is worse than none. Each link says it came
from this brief (`?fra=brev&b=<id>`), so the app can count the tap — for a
user who has said yes to that (`metrics.tap`). No open pixel.

**A decision opens without a password.** When the email is sent, each decision
gets a link of its own (`card_links`) that opens its card and decides it once,
for a week, without a login (`#godkjenn/<token>`). The stored brief stays as it
was: the links belong to one email, and a brief sent again gets new ones.

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
import card_links
import company
import config
import db
import job_runs
import mailer

log = logging.getLogger("cfo.brief_email")

# Arvaka's brand tokens (v1.0, Oct 2026), as email can carry them; the brand
# for email is written down in board/cards/email-design.md.
IVORY, WHITE, INK = "#FAFAF9", "#FFFFFF", "#0F0E0D"
GRAY_100, GRAY_200, GRAY_600, GRAY_700 = "#F2F1F0", "#E5E5E3", "#706D66", "#524F49"
BRAND_900, BRAND_700 = "#0F362A", "#135B45"
# A light is a dot and a word, never colour alone: yellow is too light for text.
LIGHT = {"green": "#16A34A", "yellow": "#EAB308", "red": "#D94636"}
# Web fonts mostly don't load in mail; these fall back as the signature does.
SERIF = "Newsreader,Georgia,'Times New Roman',serif"
SANS = "Geist,Arial,Helvetica,sans-serif"
# Replies to cfo@arvaka.no are not read until card 49.
CONTACT = "edmir@arvaka.no"
SITE = "https://arvaka.no"

# For the apps that honour it (Apple Mail, iOS Mail, Outlook for Mac). Gmail
# inverts colours itself, and keeps the inline light ones as its starting
# point. Everything that matters is inline; this only adjusts.
STYLE = """
:root{color-scheme:light dark;supported-color-schemes:light dark}
@media (prefers-color-scheme:dark){
.a-page{background:#0F0E0D!important}
.a-sheet{background:#1F1D1A!important;border-color:#33312C!important}
.a-tile{background:#33312C!important}
.a-ink{color:#F2F1F0!important}
.a-soft{color:#ADABA5!important}
.a-rule{border-color:#33312C!important}
.a-link{color:#B8C9C1!important}
.a-btn{background:#135B45!important}
.a-btn a{color:#FAFAF9!important}
}
@media (max-width:480px){
.a-pad{padding-left:20px!important;padding-right:20px!important}
.a-head{font-size:24px!important;line-height:30px!important}
}
"""


class NotWritten(RuntimeError):
    """There is no brief for this week to send."""


def subject(b: dict) -> str:
    week = b["period"].split("-W")[1].lstrip("0")
    return f"Mandagsbrevet uke {week}: {brief.LIGHTS[b['light']]}"


def _url(b: dict, link: str = "") -> str | None:
    """Where an app link («#saker/K016», or "" for the brief) is from a phone,
    marked as a tap from brief `b`; None when the app cannot be reached."""
    if not config.APP_URL:
        return None
    mark = f"?fra=brev&b={b['id']}" if b.get("id") else ""
    return f"{config.APP_URL}/{mark}{link}"


def text(b: dict) -> str:
    there = f"\n\nHele brevet og sakene: {_url(b)}" if _url(b) else ""
    return (f"{b['body']}{there}\n\n—\nMandagsbrevet fra Arvaka, skrevet "
            f"{brief._day(b['made_on'])} fra tallene i Tripletex.\n"
            f"Spørsmål? {CONTACT} · arvaka.no")


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _font(family: str, size: int, line: int, weight: int = 400,
          color: str = INK) -> str:
    return (f"font-family:{family};font-size:{size}px;line-height:{line}px;"
            f"font-weight:{weight};color:{color}")


def _label(s: str) -> str:
    return (f'<div class="a-soft" style="{_font(SANS, 11, 16, 500, GRAY_600)};'
            f'letter-spacing:.08em;text-transform:uppercase;margin:0 0 4px">'
            f'{_e(s)}</div>')


def _a(url: str | None, label: str, strong: bool = False) -> str:
    """`label` (already escaped) as a link to `url`, or as it is without one."""
    if not url:
        return label
    return (f'<a class="a-link" href="{_e(url)}" style="color:{BRAND_700};'
            f'font-weight:{500 if strong else 400};text-decoration:none">{label}</a>')


def _row(left: str, right: str = "", first: bool = False) -> str:
    """One line of a hairline list, a figure right-aligned beside it."""
    rule = "" if first else f"border-top:1px solid {GRAY_200};"
    return (f'<tr><td class="a-ink a-rule" style="{rule}padding:11px 0;'
            f'{_font(SANS, 15, 22)}">{left}</td>'
            f'<td class="a-soft a-rule" align="right" style="{rule}'
            f'padding:11px 0 11px 16px;{_font(SANS, 15, 22, 400, GRAY_700)};'
            f'white-space:nowrap;vertical-align:top;'
            f'font-variant-numeric:tabular-nums">{right}</td></tr>')


def _table(rows: str, width: str = "100%") -> str:
    width = f' width="{width}"' if width else ""
    return (f'<table role="presentation"{width} cellpadding="0" '
            f'cellspacing="0" border="0">{rows}</table>')


def _soft(s: str) -> str:
    return f'<span class="a-soft" style="color:{GRAY_700}">{s}</span>'


def _section(title: str, body: str) -> str:
    return (f'<tr><td class="a-pad" style="padding:28px 32px 0">'
            f'{_label(title)}{body}</td></tr>')


def _small(s: str, top: int = 0) -> str:
    return (f'<p class="a-soft" style="margin:{top}px 0 0;'
            f'{_font(SANS, 13, 19, 400, GRAY_600)}">{s}</p>')


def _low_point(low: dict) -> str:
    """The tightest week as a figure, the rest of its own sentence beneath."""
    rest = low["text"].split(" — ", 1)[1] if " — " in low["text"] else low["text"]
    when = low["week"] + (f", fra {brief._day(low['start'])}" if low.get("start") else "")
    return (f'<tr><td class="a-pad" style="padding:20px 32px 0">'
            + _table(f'<tr><td class="a-tile" style="background:{GRAY_100};'
                     f'border-radius:6px;padding:16px 18px">'
                     f'{_label("Laveste punkt · " + when)}'
                     f'<div class="a-ink" style="{_font(SANS, 28, 34, 300)};'
                     f'font-variant-numeric:tabular-nums;letter-spacing:-.5px">'
                     f'{_e(brief._kr(low["amount"]))} kr</div>'
                     f'<div class="a-soft" style="{_font(SANS, 14, 20, 400, GRAY_700)};'
                     f'margin:4px 0 0">{_e(rest)}</div></td></tr>')
            + '</td></tr>')


def _decisions(b: dict, links: dict[str, str]) -> tuple[str, str]:
    d = b["decisions"]
    if not d["count"]:
        return "Trenger deg", (f'<p class="a-ink" style="margin:6px 0 0;'
                               f'{_font(SERIF, 20, 28)}">Ingenting trenger deg denne uka.</p>')
    rows = []
    for i, c in enumerate(d["top"]):
        amount = c.get("amount")
        # Most titles say their amount already; said twice it reads as two.
        said = amount and brief._kr(amount) in c["title"]
        figure = f"{_e(brief._kr(amount))} kr" if amount and not said else ""
        link = f"#godkjenn/{links[c['id']]}" if c["id"] in links else c.get("link")
        href = _url(b, link) if link else None
        act = (f'<div style="margin:4px 0 0;font-size:14px;line-height:20px">'
               f'{_a(href, "Avgjør &rarr;", strong=True)}</div>' if href else "")
        rows.append(_row(f"{_e(c['title'])}{act}", figure, first=i == 0))
    if d["more"]:
        rows.append(_row(_soft(_a(_url(b, "#saker"),
                                  f'og {d["more"]} til i appen, under Saker'))))
    return f"Trenger deg ({d['count']})", _table("".join(rows))


def render_html(b: dict, links: dict[str, str] | None = None) -> str:
    """The email. `links` is {card id: token} from `card_links.mint`: a decision
    with one links to its card without a login, one without to `#saker/<id>`."""
    links = links or {}
    week = b["period"].split("-W")[1].lstrip("0")
    word = brief.LIGHTS[b["light"]]

    changed = (_table("".join(_row(_e(c), first=i == 0)
                              for i, c in enumerate(b["changed"])))
               if b["changed"] else
               _table(_row(_soft("Ingen endringer verdt å nevne."), first=True)))
    decisions_title, decisions = _decisions(b, links)

    app = _url(b)
    button = ('<tr><td class="a-pad" style="padding:28px 32px 0">'
              + _table(f'<tr><td class="a-btn" bgcolor="{BRAND_900}" '
                       f'style="background:{BRAND_900};border-radius:9999px">'
                       f'<a href="{_e(app)}" style="display:inline-block;padding:12px 24px;'
                       f'{_font(SANS, 14, 16, 500, IVORY)};text-decoration:none;'
                       f'border-radius:9999px">Åpne brevet i appen</a></td></tr>',
                       width="")
              + '</td></tr>') if app else ""

    books = _small(_e(b["books"]["text"]))
    books += "".join(_small(f"&middot;&nbsp;{_e(x)}", 2) for x in b["books"]["lines"])
    books += _small(_e(b["accuracy"]["text"]), 8)

    # What the inbox shows beside the subject, instead of the masthead.
    preheader = f"{word} — {b['sentence']} {b['low_point']['text']}"

    return f"""<!doctype html>
<html lang="nb"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{_e(subject(b))}</title>
<style>{STYLE}</style></head>
<body class="a-page" style="margin:0;padding:0;background:{IVORY}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{_e(preheader)}</div>
<table class="a-page" role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{IVORY}">
<tr><td align="center" style="padding:24px 12px 32px">
<table class="a-sheet" role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
 style="max-width:600px;background:{WHITE};border:1px solid {GRAY_200};border-radius:6px">
<tr><td class="a-pad" style="padding:28px 32px 0">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td class="a-ink" style="{_font(SERIF, 26, 30)};letter-spacing:-1px;white-space:nowrap">Arvaka<span class="a-link" style="color:{BRAND_700}">.</span></td>
<td class="a-soft" align="right" style="{_font(SANS, 13, 30, 400, GRAY_600)};white-space:nowrap">Mandag, uke {_e(week)}</td>
</tr></table>
<div class="a-rule" style="border-top:1px solid {GRAY_200};margin:20px 0 0;font-size:0;line-height:0">&nbsp;</div>
</td></tr>
<tr><td class="a-pad" style="padding:24px 32px 0">
<div class="a-ink" style="{_font(SANS, 12, 16, 500)};letter-spacing:.08em"><span style="color:{LIGHT[b['light']]};font-size:14px">&#9679;</span>&nbsp;{_e(word)}</div>
<h1 class="a-ink a-head" style="margin:10px 0 0;{_font(SERIF, 28, 34)};letter-spacing:-.5px">{_e(b['sentence'])}</h1>
</td></tr>
{_low_point(b['low_point'])}
{_section("Endret siden forrige mandag", changed)}
{_section(decisions_title, decisions)}
{button}
<tr><td class="a-pad" style="padding:28px 32px">
<div class="a-rule" style="border-top:1px solid {GRAY_200};padding:16px 0 0">{books}</div>
</td></tr>
</table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px">
<tr><td class="a-pad" style="padding:20px 32px 0">
<p class="a-soft" style="margin:0;{_font(SANS, 12, 18, 400, GRAY_600)}">Mandagsbrevet fra Arvaka, skrevet {_e(brief._day(b['made_on']))} fra tallene i Tripletex.</p>
<p class="a-soft" style="margin:4px 0 0;{_font(SANS, 12, 18, 400, GRAY_600)}">Spørsmål? {_a("mailto:" + CONTACT, CONTACT)}&nbsp;&middot;&nbsp;{_a(SITE, "arvaka.no")}</p>
</td></tr></table>
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
    # Only where a phone can reach the app, and for a brief that is kept.
    links = (card_links.mint([c["id"] for c in b["decisions"]["top"]], b["id"])
             if config.APP_URL else {})
    # Per brief and per attempt by hand: a scheduled retry of the same brief
    # carries the same key and is never delivered twice; a send someone asked
    # for is a new email.
    key = f"weekly-brief-{b['id']}" + (f"-{uuid.uuid4().hex}" if force else "")
    mail_id = await mailer.send(to, subject(b), render_html(b, links), text(b), key)
    _mark_sent(b["id"], to, mail_id)
    return {"skipped": False, "period": b["period"], "to": to, "id": mail_id}
