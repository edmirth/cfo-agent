"""The gate: no `/api` route answers without the CEO signed in.

Tokens are minted here with a key the test makes, as Supabase would sign
them, and the app is called through ASGI directly: the request goes through
the same middleware a browser's does.
"""
import asyncio
import json
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

import auth
import config
import main

ISSUER = f"{config.SUPABASE_URL}/auth/v1"
KEY = ec.generate_private_key(ec.SECP256R1())
KID = "test-key-1"


def _trust_test_key():
    auth._keys.keys = {KID: KEY.public_key()}
    auth._keys.fetched = auth._keys.tried = time.monotonic()


def _token(email="ceo@example.no", key=KEY, kid=KID, alg="ES256", **over) -> str:
    now = int(time.time())
    claims = {"sub": "user-1", "email": email, "aud": "authenticated",
              "iss": ISSUER, "iat": now, "exp": now + 3600, "role": "authenticated"}
    claims.update(over)
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def _call(path: str, token: str | None = None, method: str = "GET"):
    """One request through the app. Returns (status, json body or None)."""
    headers = [(b"authorization", f"Bearer {token}".encode())] if token else []
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": headers, "client": ("127.0.0.1", 1),
             "server": ("127.0.0.1", 8000), "root_path": ""}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(main.app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


# ------------------------------------------------------------------ the gate
def test_no_token_no_answer():
    status, body = _call("/api/presets")
    assert status == 401 and body["login"] is True
    assert body["error"] == "Du må logge inn."


def test_every_api_route_but_the_login_config_is_behind_the_gate():
    # Fail closed: walked from the app itself, so a route added later is
    # checked without this test being touched.
    checked = 0
    for route in main.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or path in auth.OPEN:
            continue
        concrete = path.replace("{", "").replace("}", "")
        for method in sorted(getattr(route, "methods", None) or {"GET"}):
            status, _ = _call(concrete, method=method)
            assert status == 401, f"{method} {path} answered {status} without a login"
            checked += 1
    assert checked >= 20, checked


def test_the_login_config_is_open_and_holds_no_secret():
    status, body = _call("/api/auth/config")
    assert status == 200
    assert body == {"enabled": True, "provider": "supabase",
                    "url": config.SUPABASE_URL, "anon_key": config.SUPABASE_ANON_KEY}


def test_the_page_itself_is_not_behind_the_gate():
    # The login screen is part of the page; it has to load to be shown.
    status, _ = _call("/")
    assert status != 401


def test_the_ceo_signed_in_gets_in():
    _trust_test_key()
    status, body = _call("/api/presets", _token())
    assert status == 200 and body["presets"]
    # Case is not identity.
    assert _call("/api/presets", _token(email="CEO@Example.no"))[0] == 200


# ------------------------------------------------------------- what is refused
def test_signed_in_but_not_on_the_list_is_403_not_a_new_login():
    _trust_test_key()
    status, body = _call("/api/presets", _token(email="someone@else.no"))
    assert status == 403 and body["login"] is False
    assert "ikke tilgang" in body["error"]


def test_an_expired_token_asks_for_a_new_login():
    _trust_test_key()
    old = int(time.time()) - 7200
    status, body = _call("/api/presets", _token(iat=old, exp=old + 3600))
    assert status == 401 and "gått ut" in body["error"]


def test_a_token_for_another_project_or_audience_is_refused():
    _trust_test_key()
    assert _call("/api/presets", _token(iss="https://other.supabase.co/auth/v1"))[0] == 401
    assert _call("/api/presets", _token(aud="anon"))[0] == 401


def test_a_token_signed_with_another_key_is_refused():
    _trust_test_key()
    other = ec.generate_private_key(ec.SECP256R1())
    assert _call("/api/presets", _token(key=other))[0] == 401


def test_unsigned_and_key_confusion_tokens_are_refused():
    _trust_test_key()
    claims = jwt.decode(_token(), options={"verify_signature": False})
    unsigned = jwt.encode(claims, None, algorithm="none")
    assert _call("/api/presets", unsigned)[0] == 401
    # HS256 "signed" with something public, while no shared secret is set.
    real = config.SUPABASE_JWT_SECRET
    config.SUPABASE_JWT_SECRET = ""
    try:
        forged = jwt.encode(claims, config.SUPABASE_ANON_KEY + "x" * 32, algorithm="HS256")
        assert _call("/api/presets", forged)[0] == 401
    finally:
        config.SUPABASE_JWT_SECRET = real
    assert _call("/api/presets", "not-a-token")[0] == 401


def test_a_project_on_the_legacy_shared_secret_still_signs_in():
    real = config.SUPABASE_JWT_SECRET
    config.SUPABASE_JWT_SECRET = "legacy-secret-" + "s" * 32
    try:
        token = _token(key=config.SUPABASE_JWT_SECRET, alg="HS256")
        assert _call("/api/presets", token)[0] == 200
    finally:
        config.SUPABASE_JWT_SECRET = real


# ------------------------------------------------------------------ the keys
def test_an_unknown_key_is_fetched_once_a_minute_at_most():
    _trust_test_key()
    calls = []
    real = auth._keys._fetch

    async def fetch():
        calls.append(1)
        auth._keys.tried = time.monotonic()
    auth._keys._fetch = fetch
    try:
        auth._keys.tried = time.monotonic() - auth.JWKS_RETRY_S - 1
        for _ in range(5):
            assert _call("/api/presets", _token(kid="rotated"))[0] == 401
        assert len(calls) == 1
    finally:
        auth._keys._fetch = real


def test_a_rotated_key_is_picked_up():
    new = ec.generate_private_key(ec.SECP256R1())
    _trust_test_key()
    real = auth._keys._fetch

    async def fetch():
        auth._keys.tried = time.monotonic()
        auth._keys.keys = {"rotated": new.public_key()}
        auth._keys.fetched = time.monotonic()
    auth._keys._fetch = fetch
    try:
        auth._keys.tried = time.monotonic() - auth.JWKS_RETRY_S - 1
        assert _call("/api/presets", _token(key=new, kid="rotated"))[0] == 200
    finally:
        auth._keys._fetch = real


# ------------------------------------------------------------------ starting
def test_a_server_without_login_set_up_does_not_start():
    real = config.SUPABASE_URL, config.OWNER_EMAILS
    config.SUPABASE_URL, config.OWNER_EMAILS = "", frozenset()
    try:
        auth.check_config()
        raise AssertionError("started without a login")
    except SystemExit as exc:
        assert "SUPABASE_URL, CFO_OWNER_EMAIL mangler" in str(exc)
    finally:
        config.SUPABASE_URL, config.OWNER_EMAILS = real


def test_off_on_purpose_runs_open():
    real = config.AUTH
    config.AUTH = "off"
    try:
        auth.check_config()
        assert _call("/api/presets")[0] == 200
        assert _call("/api/auth/config")[1] == {"enabled": False}
    finally:
        config.AUTH = real
