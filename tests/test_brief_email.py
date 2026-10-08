"""The Monday brief by email: what goes out, to whom, and never twice.

Resend is stood in for: either `mailer.send` is replaced to record what it
was asked to send, or Resend's HTTP API is played back through a mock
transport, so the real request the module builds is the one checked.
"""
import asyncio
import json
from datetime import date

import brief
import brief_email
import company
import config
import job_runs
import mailer
import scheduler
from tests import _tmp

MON = date(2026, 10, 12)

BRIEF = {
    "light": "yellow", "why": "…", "sentence": "Stramt i desember, men ingen fare nå.",
    "low_point": {"week": "Uke 50", "start": "2026-12-07", "amount": 932040.0,
                  "floor": 1143813.0, "under_floor": True,
                  "text": "Laveste punkt: uke 50 (fra 7. desember), 932 040 kr — "
                          "211 773 kr under gulvet på 1 143 813 kr."},
    "changed": ["Kundefordringer: 2 710 464 kr, fra 2 614 608 kr."],
    "decisions": {"count": 4, "more": 1, "top": [
        {"id": "K016", "title": "Seby AS er 50 dager på etterskudd med 57 056 kr",
         "amount": 57056.0, "link": "#saker/K016"},
        {"id": "K017", "title": "Purr <Backe & Co>", "amount": 23813.0,
         "link": "#saker/K017"},
        {"id": "K018", "title": "Avklar uavstemt innbetaling", "amount": None,
         "link": "#saker/K018"}]},
    "books": {"condition": "provisional", "lines": ["2 bilag ligger ubokført."],
              "text": "Bøkene: Tallene er foreløpige."},
    "accuracy": {"scored": False, "text": "Treffsikkerhet: ikke målt ennå."},
    "written_by": "model", "period": brief.period(MON), "made_on": MON.isoformat(),
    "forecast_partial": False, "unverified": [],
}


def _keep(**over) -> dict:
    b = dict(BRIEF, **over)
    b["body"] = brief.render(b)
    b["id"] = brief.save(b)
    return b


class _Outbox:
    """Stands in for `mailer.send`: records each email, or raises."""

    def __init__(self, *outcomes):
        self.sent, self.outcomes = [], list(outcomes)

    async def __call__(self, to, subject, html, text, key):
        self.sent.append({"to": to, "subject": subject, "html": html,
                          "text": text, "key": key})
        out = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(out, BaseException):
            raise out
        return f"mail-{len(self.sent)}"


def _with(outbox):
    real = mailer.send
    mailer.send = outbox
    return lambda: setattr(mailer, "send", real)


def _as(trigger):
    return job_runs.trigger.set(trigger)


# ------------------------------------------------------------------ recipients
def test_recipients_default_to_whoever_may_sign_in():
    _tmp.store(company, "COMPANY_FILE")
    assert company.recipients() == sorted(config.OWNER_EMAILS)


def test_recipients_from_the_rulebook_and_a_typo_is_said_not_sent_to():
    path = _tmp.store(company, "COMPANY_FILE")
    path.write_text("---\nbrev_mottakere: Ceo@Example.no, regnskap@firma.no; "
                    "ikke-en-adresse, ceo@example.no\n---\nOm oss.\n", encoding="utf-8")
    company._cache.clear()
    data = company.load(force=True)
    assert company.recipients() == ["ceo@example.no", "regnskap@firma.no"]
    assert any("«ikke-en-adresse» er ikke en e-postadresse" in n for n in data["notes"])


# ----------------------------------------------------------------- the email
def test_the_email_is_complete_on_its_own_and_reads_on_a_phone():
    b = dict(BRIEF, body=brief.render(BRIEF))
    page = brief_email.render_html(b)
    assert brief_email.subject(b) == "Mandagsbrevet uke 42: GUL"
    for said in ("Stramt i desember", "932 040 kr", "Kundefordringer",
                 "Trenger deg (4)", "og 1 til i appen", "2 bilag ligger ubokført.",
                 "Treffsikkerhet", 'name="viewport"', "max-width:560px"):
        assert said in page, said
    # No links: the app cannot be reached from a phone yet.
    assert "<a " not in page and "href" not in page
    # A title that says its amount is not followed by it again; one that does
    # not, is.
    assert page.count("57 056 kr") == 1 and "· 23 813 kr" in page
    # What a card says is text, not markup.
    assert "Purr &lt;Backe &amp; Co&gt;" in page
    # Well under the size at which Gmail cuts a message off.
    assert len(page.encode()) < 30_000
    assert brief_email.text(b).startswith("GUL — Stramt i desember")


# ------------------------------------------------------------------ sending
def test_sent_once_a_week_by_the_schedule_and_marked_sent():
    _tmp.db()
    _tmp.store(company, "COMPANY_FILE")
    b = _keep()
    outbox = _Outbox()
    undo, token = _with(outbox), _as("schedule")
    try:
        first = asyncio.run(brief_email.send(MON))
        again = asyncio.run(brief_email.send(MON))
    finally:
        undo()
        job_runs.trigger.reset(token)
    assert not first["skipped"] and first["to"] == sorted(config.OWNER_EMAILS)
    assert again["skipped"] and len(outbox.sent) == 1
    assert outbox.sent[0]["key"] == f"weekly-brief-{b['id']}"
    kept = brief.latest(MON)
    assert kept["status"] == "sent" and kept["sent"]["id"] == "mail-1"


def test_a_scheduled_retry_carries_the_same_key_so_it_is_never_delivered_twice():
    _tmp.db()
    _tmp.store(company, "COMPANY_FILE")
    _keep()
    outbox = _Outbox(mailer.MailError("Fikk ikke kontakt med Resend."), None)
    undo, token = _with(outbox), _as("schedule")
    try:
        try:
            asyncio.run(brief_email.send(MON))
            raise AssertionError("a failed send passed")
        except mailer.MailError:
            pass
        assert brief.latest(MON)["status"] == "final"
        asyncio.run(brief_email.send(MON))
    finally:
        undo()
        job_runs.trigger.reset(token)
    assert outbox.sent[0]["key"] == outbox.sent[1]["key"]


def test_sending_by_hand_always_sends_as_a_new_email():
    _tmp.db()
    _tmp.store(company, "COMPANY_FILE")
    _keep()
    outbox = _Outbox()
    undo, token = _with(outbox), _as("user")
    try:
        asyncio.run(brief_email.send(MON))
        asyncio.run(brief_email.send(MON))
    finally:
        undo()
        job_runs.trigger.reset(token)
    assert len(outbox.sent) == 2 and outbox.sent[0]["key"] != outbox.sent[1]["key"]


def test_last_weeks_brief_is_not_sent_as_this_weeks():
    _tmp.db()
    _keep()
    try:
        asyncio.run(brief_email.send(date(2026, 10, 19)))
        raise AssertionError("last week's brief went out")
    except brief_email.NotWritten as exc:
        assert "ikke skrevet" in str(exc)


def test_the_mail_step_fails_out_loud_and_runs_after_the_brief():
    assert scheduler.JOBS == (scheduler.MORNING, scheduler.WEEKLY, scheduler.MAIL)
    assert scheduler.MAIL.runs_on is scheduler.WEEKLY.runs_on
    _tmp.db()
    try:
        asyncio.run(scheduler._mail())
        raise AssertionError("nothing to send passed")
    except scheduler.StepFailed as exc:
        assert "ikke skrevet" in str(exc)


# ------------------------------------------------------------- the provider
def _resend(status: int, body: dict, seen: list):
    import httpx2 as httpx

    def handle(request):
        seen.append(request)
        return httpx.Response(status, json=body)
    real = mailer.httpx.AsyncClient
    mailer.httpx.AsyncClient = lambda **kw: real(transport=httpx.MockTransport(handle), **kw)
    return lambda: setattr(mailer.httpx, "AsyncClient", real)


def test_resend_is_sent_the_email_with_its_key():
    seen = []
    key = config.RESEND_API_KEY
    config.RESEND_API_KEY = "re_test"
    undo = _resend(200, {"id": "abc"}, seen)
    try:
        out = asyncio.run(mailer.send(["ceo@example.no"], "Emne", "<p>x</p>", "x", "k-1"))
    finally:
        undo()
        config.RESEND_API_KEY = key
    assert out == "abc"
    req = seen[0]
    assert str(req.url) == mailer.API
    assert req.headers["authorization"] == "Bearer re_test"
    assert req.headers["idempotency-key"] == "k-1"
    sent = json.loads(req.content)
    assert sent["to"] == ["ceo@example.no"] and sent["from"] == config.MAIL_FROM
    assert sent["html"] == "<p>x</p>" and sent["text"] == "x"


def test_resends_refusals_are_said_in_words_to_act_on():
    key = config.RESEND_API_KEY
    config.RESEND_API_KEY = "re_test"
    cases = [(403, {"message": "You can only send testing emails to your own email "
                               "address (a@b.no)."}, "kontoens egen e-postadresse"),
             (401, {"message": "API key is invalid"}, "RESEND_API_KEY"),
             (429, {"message": "Too many requests"}, "for mye på kort tid")]
    try:
        for status, body, said in cases:
            undo = _resend(status, body, [])
            try:
                asyncio.run(mailer.send(["x@y.no"], "s", "h", "t", "k"))
                raise AssertionError(f"{status} passed")
            except mailer.MailError as exc:
                assert said in str(exc), (status, str(exc))
            finally:
                undo()
        config.RESEND_API_KEY = ""
        try:
            asyncio.run(mailer.send(["x@y.no"], "s", "h", "t", "k"))
            raise AssertionError("sent without a key")
        except mailer.MailError as exc:
            assert "RESEND_API_KEY mangler" in str(exc)
    finally:
        config.RESEND_API_KEY = key
