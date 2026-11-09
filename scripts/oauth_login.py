#!/usr/bin/env python
"""Engangs OAuth-innlogging mot Tripletex MCP.

Åpner nettleseren for innlogging og lagrer et refresh token i .env. Klienten
(TRIPLETEX_CLIENT_ID) i .env brukes om igjen, så etter en utløpt innlogging er
det bare refresh-tokenet som er nytt. Finnes ingen, registreres en. Er den
avvist av Tripletex, kjør med --ny-klient for å registrere en ny. Refresh-tokenet kan utløpe (det gjorde det 7. oktober 2026). Da
sier appen fra på forsiden, og dette kjøres på nytt. En app som kjører lokalt
tar den nye innloggingen i bruk med en gang; på Render må TRIPLETEX_CLIENT_ID
og TRIPLETEX_REFRESH_TOKEN fra .env inn i innstillingene der, og appen startes
på nytt.

    ./.venv/bin/python scripts/oauth_login.py
    ./.venv/bin/python scripts/oauth_login.py --ny-klient
"""
import base64
import hashlib
import html
import http.server
import re
import secrets
import socketserver
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import httpx2 as httpx

ISSUER = "https://mcp.tripletex.no"
PORT = 7337
REDIRECT = f"http://localhost:{PORT}/callback"
ENV = Path(__file__).resolve().parent.parent / ".env"

_code: dict = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _code.update({k: v[0] for k, v in q.items()})
        ok = "code" in q
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = ("<h2>Innlogging fullført</h2><p>Du kan lukke dette vinduet "
               "og gå tilbake til terminalen.</p>") if ok else \
              f"<h2>Innlogging feilet</h2><pre>{html.escape(str(q))}</pre>"
        self.write_html(msg)

    def write_html(self, body: str):
        self.wfile.write(
            f"<html><body style='font-family:system-ui;padding:3rem'>{body}</body></html>"
            .encode()
        )

    def log_message(self, *args):
        pass  # keep the terminal clean


def set_env(key: str, value: str) -> None:
    text = ENV.read_text() if ENV.exists() else ""
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    text = pattern.sub(lambda _: line, text) if pattern.search(text) else text.rstrip("\n") + f"\n{line}\n"
    ENV.write_text(text)
    ENV.chmod(0o600)


def get_env(key: str) -> str:
    text = ENV.read_text() if ENV.exists() else ""
    m = re.search(rf"^{re.escape(key)}=(.*)$", text, re.MULTILINE)
    return m.group(1).strip().strip("'\"") if m else ""


NEW_CLIENT = ("     Klienten er ikke gyldig lenger. Registrer en ny:\n\n"
              "     ./.venv/bin/python scripts/oauth_login.py --ny-klient")


def register(c: httpx.Client, meta: dict) -> str | None:
    reg = c.post(meta["registration_endpoint"], json={
        "client_name": "CFO Agent",
        "redirect_uris": [REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    })
    if reg.status_code not in (200, 201):
        print(f"     Feilet ({reg.status_code}): {reg.text[:300]}")
        return None
    return reg.json()["client_id"]


def main(argv: list[str]) -> int:
    with httpx.Client(timeout=40) as c:
        meta = c.get(f"{ISSUER}/.well-known/oauth-authorization-server").json()

        existing = "" if "--ny-klient" in argv else get_env("TRIPLETEX_CLIENT_ID")
        if existing:
            client_id = existing
            print(f"1/4  Bruker klienten fra .env: {client_id}")
        else:
            print("1/4  Registrerer klient …")
            client_id = register(c, meta)
            if not client_id:
                return 1
            print(f"     client_id {client_id}")

        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = secrets.token_urlsafe(16)

        url = meta["authorization_endpoint"] + "?" + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })

        socketserver.TCPServer.allow_reuse_address = True
        server = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        print("\n2/4  Åpner nettleseren. Logg inn i Tripletex og godkjenn.")
        print(f"     Åpnes ikke automatisk? Lim inn denne:\n\n     {url}\n")
        if existing:
            print("     Sier Tripletex at klienten er ukjent? Avbryt med Ctrl+C og kjør")
            print("     ./.venv/bin/python scripts/oauth_login.py --ny-klient\n")
        webbrowser.open(url)

        print("3/4  Venter på at du fullfører innloggingen …")
        for _ in range(600):
            if _code:
                break
            threading.Event().wait(0.5)
        server.shutdown()

        if "code" not in _code:
            print(f"     Ingen kode mottatt. Svar: {_code or 'tidsavbrudd'}")
            if existing and _code.get("error") in ("invalid_client", "unauthorized_client"):
                print(NEW_CLIENT)
            return 1
        if _code.get("state") != state:
            print("     State stemmer ikke — avbryter av sikkerhetshensyn.")
            return 1

        print("4/4  Veksler inn koden …")
        tok = c.post(meta["token_endpoint"], data={
            "grant_type": "authorization_code",
            "code": _code["code"],
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if tok.status_code != 200:
            print(f"     Feilet ({tok.status_code}): {tok.text[:300]}")
            if existing and "invalid_client" in tok.text:
                print(NEW_CLIENT)
            return 1

        d = tok.json()
        refresh = d.get("refresh_token")
        if not refresh:
            print(f"     Fikk access token, men ikke refresh token. Felter: {sorted(d)}")
            return 1

        if not existing:
            set_env("TRIPLETEX_CLIENT_ID", client_id)
        set_env("TRIPLETEX_REFRESH_TOKEN", refresh)
        print("\n✓ Lagret i .env")
        print(f"  access token  : {len(d.get('access_token',''))} tegn, "
              f"utløper om {d.get('expires_in')} s")
        print(f"  refresh token : {len(refresh)} tegn")
        what = ("TRIPLETEX_REFRESH_TOKEN (klienten er den samme)" if existing
                else "TRIPLETEX_CLIENT_ID og TRIPLETEX_REFRESH_TOKEN")
        print(f"\nKjører appen på Render: legg {what}")
        print("fra .env inn i innstillingene der, og start appen på nytt. Ikke kjør")
        print("check_tokens.py eller appen her først: de fornyer innloggingen, og da")
        print("virker ikke kopien på Render.")
        print("\nKjører appen her, tar den i bruk den nye innloggingen med en gang.")
        print("Sjekk den med ./.venv/bin/python scripts/check_tokens.py")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
