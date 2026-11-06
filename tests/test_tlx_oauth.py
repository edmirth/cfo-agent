"""The Tripletex login survives a restart where there is no .env to write to.

On Render the refresh token comes from a setting the server cannot change.
Tripletex rotates it on renewal, so the rotated one has to be kept on the disk,
and read back instead of the setting after a restart.
"""
import asyncio
import json
import stat
import tempfile
from pathlib import Path

import config
import tlx_oauth


def _manager(setting: str, store: Path | None = None):
    config.TRIPLETEX_REFRESH_TOKEN = setting
    store = store or Path(tempfile.mkdtemp()) / "tripletex.json"
    return tlx_oauth.TokenManager(store=store), store


def _restore(saved):
    config.TRIPLETEX_REFRESH_TOKEN, config.TRIPLETEX_CLIENT_ID = saved


class _Tripletex:
    """Answers a renewal the way Tripletex does: a new access and refresh token."""

    sent: list[str] = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data, headers):
        _Tripletex.sent.append(data["refresh_token"])

        class R:
            status_code = 200

            @staticmethod
            def json():
                return {"access_token": "at-1", "expires_in": 3600,
                        "refresh_token": "rotated-1"}
        return R()


def test_the_first_start_keeps_the_setting_on_the_disk():
    saved = config.TRIPLETEX_REFRESH_TOKEN, config.TRIPLETEX_CLIENT_ID
    try:
        tm, store = _manager("from-settings")
        assert tm._current_refresh() == "from-settings"
        assert json.loads(store.read_text())["refresh_token"] == "from-settings"
        # Only the server may read it.
        assert stat.S_IMODE(store.stat().st_mode) == 0o600
    finally:
        _restore(saved)


def test_a_rotated_token_is_used_after_a_restart_not_the_old_setting():
    saved = config.TRIPLETEX_REFRESH_TOKEN, config.TRIPLETEX_CLIENT_ID
    original = tlx_oauth.httpx.AsyncClient
    tlx_oauth.httpx.AsyncClient = _Tripletex
    _Tripletex.sent = []
    try:
        config.TRIPLETEX_CLIENT_ID = "client"
        tm, store = _manager("from-settings")
        tm._client_id = "client"
        assert asyncio.run(tm.access_token()) == "at-1"
        assert _Tripletex.sent == ["from-settings"]
        assert json.loads(store.read_text())["refresh_token"] == "rotated-1"

        # The restart: a new process, the setting still the old token.
        after, _ = _manager("from-settings", store)
        assert after._current_refresh() == "rotated-1"
    finally:
        tlx_oauth.httpx.AsyncClient = original
        _restore(saved)


def test_a_new_login_in_the_settings_replaces_the_stored_token():
    saved = config.TRIPLETEX_REFRESH_TOKEN, config.TRIPLETEX_CLIENT_ID
    try:
        tm, store = _manager("first-login")
        tm._current_refresh()
        tm._persist_refresh("rotated-since")

        # The login expired; someone logged in again and put the new token in.
        again, _ = _manager("second-login", store)
        assert again._current_refresh() == "second-login"
        assert json.loads(store.read_text())["refresh_token"] == "second-login"

        # And after the next restart it stays: the file now started from it.
        later, _ = _manager("second-login", store)
        assert later._current_refresh() == "second-login"
    finally:
        _restore(saved)


def test_the_stored_token_is_kept_if_the_setting_is_removed():
    saved = config.TRIPLETEX_REFRESH_TOKEN, config.TRIPLETEX_CLIENT_ID
    try:
        tm, store = _manager("first-login")
        tm._current_refresh()
        tm._persist_refresh("rotated-since")
        empty, _ = _manager("", store)
        assert empty._current_refresh() == "rotated-since"
    finally:
        _restore(saved)


def test_a_damaged_file_falls_back_to_the_setting():
    saved = config.TRIPLETEX_REFRESH_TOKEN, config.TRIPLETEX_CLIENT_ID
    try:
        store = Path(tempfile.mkdtemp()) / "tripletex.json"
        store.write_text("{half a fi")
        tm, _ = _manager("from-settings", store)
        assert tm._current_refresh() == "from-settings"
    finally:
        _restore(saved)


# ------------------------------------------------- a login that has died
class _Dead:
    """Answers a renewal the way Tripletex did on 2026-10-07, and counts."""

    sent: list[str] = []
    error = "invalid_grant"

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data, headers):
        _Dead.sent.append(data["refresh_token"])
        await asyncio.sleep(0)          # let the others queue on the lock

        class R:
            status_code = 400
            text = ""

            @staticmethod
            def json():
                return {"error": _Dead.error,
                        "error_description": "Refresh token expired - please re-authenticate"}
        return R()


def _dead_manager(env_text: str = ""):
    config.TRIPLETEX_CLIENT_ID = "client"
    tm, store = _manager("from-settings")
    env = store.parent / ".env"
    if env_text:
        env.write_text(env_text)
    tm._env = env
    tm._client_id = "client"
    return tm, env


async def _many(tm, n: int) -> list:
    return await asyncio.gather(*(tm.access_token() for _ in range(n)),
                                return_exceptions=True)


def test_thirty_waiting_requests_make_one_renewal_not_thirty():
    saved = config.TRIPLETEX_REFRESH_TOKEN, config.TRIPLETEX_CLIENT_ID
    original = tlx_oauth.httpx.AsyncClient
    tlx_oauth.httpx.AsyncClient, _Dead.sent, _Dead.error = _Dead, [], "invalid_grant"
    try:
        tm, _ = _dead_manager()
        out = asyncio.run(_many(tm, 30))
        assert _Dead.sent == ["from-settings"]
        # Every one of them says the same thing: what Tripletex said, and the fix.
        assert all(isinstance(e, tlx_oauth.OAuthError) for e in out)
        assert len({str(e) for e in out}) == 1
        assert "Refresh token expired" in str(out[0]) and "oauth_login.py" in str(out[0])
        # And the next page load does not ask again either.
        asyncio.run(_many(tm, 5))
        assert len(_Dead.sent) == 1
        assert tm.status()["login"] == "expired"
    finally:
        tlx_oauth.httpx.AsyncClient = original
        _restore(saved)


def test_a_wrong_client_is_dead_too_but_a_tripletex_hiccup_is_not():
    saved = config.TRIPLETEX_REFRESH_TOKEN, config.TRIPLETEX_CLIENT_ID
    original = tlx_oauth.httpx.AsyncClient
    tlx_oauth.httpx.AsyncClient, _Dead.sent = _Dead, []
    try:
        _Dead.error = "invalid_client"
        tm, _ = _dead_manager()
        asyncio.run(_many(tm, 3))
        assert len(_Dead.sent) == 1 and tm.status()["login"] == "expired"

        _Dead.sent, _Dead.error = [], "server_error"
        tm, _ = _dead_manager()
        asyncio.run(_many(tm, 3))
        assert len(_Dead.sent) == 3 and tm.status()["login"] == "untested"
    finally:
        tlx_oauth.httpx.AsyncClient = original
        _restore(saved)


def test_a_new_login_in_env_is_tried_at_once_without_a_restart():
    saved = config.TRIPLETEX_REFRESH_TOKEN, config.TRIPLETEX_CLIENT_ID
    original = tlx_oauth.httpx.AsyncClient
    tlx_oauth.httpx.AsyncClient, _Dead.sent, _Dead.error = _Dead, [], "invalid_grant"
    try:
        tm, env = _dead_manager("TRIPLETEX_CLIENT_ID=client\n"
                                "TRIPLETEX_REFRESH_TOKEN=from-settings\n")
        asyncio.run(_many(tm, 2))
        assert _Dead.sent == ["from-settings"]
        # The same .env again is the same dead login: still no call.
        asyncio.run(_many(tm, 2))
        assert len(_Dead.sent) == 1

        # The login script has run: a new client and refresh token in .env.
        env.write_text("TRIPLETEX_CLIENT_ID=client-2\n"
                       "TRIPLETEX_REFRESH_TOKEN=new-login\n")
        tlx_oauth.httpx.AsyncClient, _Tripletex.sent = _Tripletex, []
        assert asyncio.run(tm.access_token()) == "at-1"
        assert _Tripletex.sent == ["new-login"] and tm._client_id == "client-2"
        assert tm.status() == {"login": "ok"}
    finally:
        tlx_oauth.httpx.AsyncClient = original
        _restore(saved)


def test_the_login_says_whether_it_is_missing():
    saved = config.TRIPLETEX_REFRESH_TOKEN, config.TRIPLETEX_CLIENT_ID
    try:
        config.TRIPLETEX_CLIENT_ID = ""
        tm, _ = _manager("")
        tm._env = Path(tempfile.mkdtemp()) / ".env"
        st = tm.status()
        assert st["login"] == "missing" and "oauth_login.py" in st["fix"]
    finally:
        _restore(saved)


def test_on_the_server_the_fix_says_where_the_new_login_goes():
    saved = config.HOSTED
    try:
        config.HOSTED = False
        assert "Render" not in tlx_oauth.login_fix()
        config.HOSTED = True
        fix = tlx_oauth.login_fix()
        assert "oauth_login.py" in fix and "TRIPLETEX_REFRESH_TOKEN" in fix and "Render" in fix
    finally:
        config.HOSTED = saved


def test_a_front_page_panel_names_a_dead_login_not_a_calculation():
    import main
    said = main._panel(tlx_oauth.OAuthError("Kunne ikke fornye Tripletex-tilgangen (400)"),
                       "Nøkkeltallene")["error"]
    assert said.startswith("Nøkkeltallene kunne ikke hentes nå. "
                           "Tripletex-innloggingen virker ikke")
    # As commitments.py wraps it.
    wrapped = RuntimeError("Kunne ikke lese saldobalansen: Kjør: ./.venv/bin/python "
                           "scripts/oauth_login.py")
    assert "Tripletex-innloggingen virker ikke" in main._panel(wrapped, "Forpliktelsene")["error"]


def test_health_reports_the_tripletex_login():
    import main
    out = asyncio.run(main.health())
    assert out["tripletex"]["login"] in ("ok", "expired", "missing", "untested", "demo")
