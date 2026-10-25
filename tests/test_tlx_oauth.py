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
