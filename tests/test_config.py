"""Settings a host lists but leaves empty fall back like settings left out.

Render's Blueprint lists every setting it asks for, and one never filled in
reaches the server as "". `os.getenv(name, default)` keeps that "", and an
email with no sender is one Resend refuses. Config is read at import, so each
case runs in a process of its own.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = ("import sys; sys.path.insert(0, 'backend'); import config; "
         "print('RESULT', repr(config.MAIL_FROM), repr(config.COMPANY_NAME))")


def _read(**settings) -> str:
    env = {**os.environ, **settings}
    r = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=60)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT ")), None)
    assert line, r.stderr[-2000:]
    return line[7:]


def test_an_empty_sender_and_company_name_fall_back_to_the_defaults():
    assert _read(CFO_MAIL_FROM="", COMPANY_NAME="") == \
        "'CFO <onboarding@resend.dev>' 'Selskapet'"


def test_a_sender_that_is_set_is_kept():
    assert _read(CFO_MAIL_FROM="CFO <cfo@arvaka.no>", COMPANY_NAME="Lindeskar AS") == \
        "'CFO <cfo@arvaka.no>' 'Lindeskar AS'"
