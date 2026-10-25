"""Who may open the app: the CEO, signed in, and nobody else.

Without this, anyone who reaches the port gets the CFO and the company's
whole ledger. This is the one module that knows how a person is signed in.

**Supabase signs in; this server decides who gets in.** The browser signs in
with Supabase — password, or a login link by email — and sends the access
token it gets on every `/api` call. Here the token is checked locally: the
signature against the project's published keys (or the legacy shared secret),
then issuer, audience and expiry. A valid token is not enough: its email must
be one of `CFO_OWNER_EMAIL`. Supabase knows who someone is; whether they may
see this company's books is ours to say.

**Fail closed.** The check is a middleware in front of every `/api/*` route,
not a dependency each route has to remember: a route added tomorrow is
covered today. `/api/auth/config` is the one open route — it hands the browser
the project URL and its public key, which it needs before anyone can sign in.
A server without auth configured does not start, unless `CFO_AUTH=off` says
on purpose that it should run open.

**Restarts.** Nothing is held in this process. The session is Supabase's
signed token, refreshed in the browser, so a restart logs no one out.

**Moving off Supabase.** Replace `verify` and `public_config`; the middleware,
the allowlist and the frontend's token handling stay. A BankID or Vipps login
later is another issuer for `verify` to accept.
"""
import asyncio
import logging
import time
from dataclasses import dataclass

import httpx2 as httpx
import jwt
from fastapi import Request
from fastapi.responses import JSONResponse

import config

log = logging.getLogger("cfo.auth")

OPEN = frozenset({"/api/auth/config"})
AUDIENCE = "authenticated"
LEEWAY_S = 30                    # clock skew between us and Supabase
JWKS_TTL_S = 3600
JWKS_RETRY_S = 60                # an unknown key id refetches at most this often
ASYMMETRIC = ("RS256", "ES256", "EdDSA")


class Denied(Exception):
    """No entry. `status` is 401 for no or a bad token, 403 for a good token
    on someone who is not on the list. The message is for the screen."""

    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class User:
    id: str
    email: str


def enabled() -> bool:
    return config.AUTH != "off"


def check_config() -> None:
    """Refuse to start a server that would answer anyone. Called at import
    of the app, beside the Tripletex lock."""
    if not enabled():
        if config.HOSTED:
            # On a laptop off is a shortcut; on a public address it hands a
            # company's accounts to anyone who finds the URL.
            raise SystemExit(
                "CFO_AUTH=off er ikke lov på en server på nettet: da kan hvem "
                "som helst se regnskapet. Fjern innstillingen og sett opp "
                "innloggingen (SUPABASE_URL, SUPABASE_ANON_KEY, CFO_OWNER_EMAIL).")
        log.warning("CFO_AUTH=off: appen er åpen for alle som når porten.")
        return
    missing = [name for name, value in (("SUPABASE_URL", config.SUPABASE_URL),
                                        ("SUPABASE_ANON_KEY", config.SUPABASE_ANON_KEY),
                                        ("CFO_OWNER_EMAIL", config.OWNER_EMAILS))
               if not value]
    if missing:
        raise SystemExit(
            f"Innlogging er ikke satt opp: {', '.join(missing)} mangler i .env. "
            f"Se «Innlogging» i README. (CFO_AUTH=off kjører appen uten, åpen "
            f"for alle som når porten.)")


def public_config() -> dict:
    """What the browser needs to sign in. Nothing here is a secret."""
    if not enabled():
        return {"enabled": False}
    return {"enabled": True, "provider": "supabase", "url": config.SUPABASE_URL,
            "anon_key": config.SUPABASE_ANON_KEY}


# ------------------------------------------------------------ the keys
class _Keys:
    """The project's signing keys, kept for an hour. A token signed with a key
    we have not seen refetches — that is how a rotated key arrives. Any fetch
    is tried at most once a minute, so neither junk tokens nor Supabase being
    down can make every request call out; while it is down, the keys we have
    keep working."""

    def __init__(self) -> None:
        self.keys: dict[str | None, object] = {}
        self.fetched = float("-inf")     # last good fetch
        self.tried = float("-inf")       # last attempt, good or not
        self._lock = asyncio.Lock()

    def _due(self, kid: str | None, now: float) -> bool:
        wanted = kid not in self.keys or now - self.fetched >= JWKS_TTL_S
        return wanted and now - self.tried >= JWKS_RETRY_S

    async def get(self, kid: str | None):
        if self._due(kid, time.monotonic()):
            async with self._lock:
                if self._due(kid, time.monotonic()):
                    await self._fetch()
        return self.keys.get(kid)

    async def _fetch(self) -> None:
        self.tried = time.monotonic()
        url = f"{config.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001 — keep the keys we have
            log.error("Kunne ikke hente innloggingsnøklene fra Supabase: %s", exc)
            return
        keys = {}
        for k in data.get("keys") or []:
            try:
                keys[k.get("kid")] = jwt.PyJWK(k).key
            except jwt.PyJWTError as exc:
                log.warning("Hopper over en nøkkel Supabase publiserer: %s", exc)
        self.keys, self.fetched = keys, time.monotonic()


_keys = _Keys()


async def verify(token: str) -> User:
    """The signed-in person behind `token`, or Denied."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise Denied("Innloggingen er ugyldig. Logg inn på nytt.") from None
    alg = header.get("alg")
    if alg in ASYMMETRIC:
        key = await _keys.get(header.get("kid"))
        if key is None:
            raise Denied("Innloggingen er signert med en nøkkel vi ikke kjenner. "
                         "Logg inn på nytt.")
    elif alg == "HS256" and config.SUPABASE_JWT_SECRET:
        key = config.SUPABASE_JWT_SECRET
    else:
        # Never "none", and never HS256 against a public key.
        raise Denied("Innloggingen er ugyldig. Logg inn på nytt.")
    try:
        claims = jwt.decode(token, key, algorithms=[alg], audience=AUDIENCE,
                            issuer=f"{config.SUPABASE_URL}/auth/v1",
                            leeway=LEEWAY_S,
                            options={"require": ["exp", "sub", "iss", "aud"]})
    except jwt.ExpiredSignatureError:
        raise Denied("Innloggingen har gått ut. Logg inn på nytt.") from None
    except jwt.PyJWTError as exc:
        log.info("Avvist innlogging: %s", exc)
        raise Denied("Innloggingen er ugyldig. Logg inn på nytt.") from None

    email = (claims.get("email") or "").strip().lower()
    if not email or email not in config.OWNER_EMAILS:
        log.warning("Innlogget, men ikke på listen: %s", email or claims.get("sub"))
        raise Denied("Denne kontoen har ikke tilgang til selskapet.", 403)
    return User(id=claims["sub"], email=email)


def _bearer(request: Request) -> str | None:
    head = request.headers.get("authorization") or ""
    scheme, _, token = head.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


async def middleware(request: Request, call_next):
    """In front of every route: `/api/*` answers only a signed-in owner."""
    path = request.url.path
    if not enabled() or not path.startswith("/api/") or path in OPEN:
        return await call_next(request)
    token = _bearer(request)
    try:
        if token is None:
            raise Denied("Du må logge inn.")
        request.state.user = await verify(token)
    except Denied as exc:
        return JSONResponse({"error": str(exc), "login": exc.status == 401},
                            status_code=exc.status)
    return await call_next(request)
