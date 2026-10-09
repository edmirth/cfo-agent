"""Sending email. The one module that knows the provider.

Resend, through its HTTP API, with the HTTP client the project already has.
Until the product has a domain of its own, mail goes from Resend's test
sender, which delivers only to the address the Resend account was opened
with — enough while the CEO is the one recipient. Buying a domain changes
`CFO_MAIL_FROM` in `.env`, not this file. Moving off Resend changes `send`.

**Never twice.** Every send carries an idempotency key. Should a send reach
Resend and the answer be lost on the way back, the retry with the same key is
recognised as the same email and not delivered again.

**In words a person can act on.** A failure raises `MailError` with the
sentence for the front page; Resend's own words go to the log.
"""
import logging

import httpx2 as httpx

import config

log = logging.getLogger("cfo.mailer")

API = "https://api.resend.com/emails"
TIMEOUT_S = 20


class MailError(RuntimeError):
    """The email was not sent. The message is for the front page."""


def ready() -> bool:
    return bool(config.RESEND_API_KEY)


def _cause(status: int, detail: str) -> str:
    if status in (401, 403) and "testing emails to your own email" in detail:
        return ("Resend sender bare til kontoens egen e-postadresse så lenge "
                "det ikke er satt opp et eget domene. Sjekk at mottakeren er "
                "den samme e-posten Resend-kontoen ble laget med.")
    if status in (401, 403):
        return "Resend godtok ikke nøkkelen. Sjekk RESEND_API_KEY i .env."
    if status == 422:
        return "Resend avviste e-posten. Detaljene står i serverloggen."
    if status == 429:
        return "Resend sier det er sendt for mye på kort tid. Prøver igjen senere."
    return "Resend svarte ikke som det skulle. Prøver igjen senere."


async def send(to: list[str], subject: str, html: str, text: str,
               key: str) -> str:
    """Send one email. Returns Resend's id for it."""
    if not ready():
        raise MailError("E-post er ikke satt opp: RESEND_API_KEY mangler i .env.")
    if not to:
        raise MailError("Ingen mottakere. Sett brev_mottakere under Selskapet.")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            r = await client.post(API, json={
                "from": config.MAIL_FROM, "to": to, "subject": subject,
                "html": html, "text": text},
                headers={"Authorization": f"Bearer {config.RESEND_API_KEY}",
                         "Idempotency-Key": key})
    except httpx.HTTPError as exc:
        log.error("Resend kunne ikke nås: %s", exc)
        raise MailError("Fikk ikke kontakt med Resend. Prøver igjen senere.") from exc
    if r.status_code >= 300:
        log.error("Resend svarte %s: %s", r.status_code, r.text[:500])
        raise MailError(_cause(r.status_code, r.text))
    sent = r.json().get("id") or ""
    log.info("E-post sendt til %s (%s)", ", ".join(to), sent)
    return sent
