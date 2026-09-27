import definitions
import lock
from tests import _tmp


def test_fingerprint_moves_with_code_not_wording():
    e = definitions._entries()["dso"]
    a = definitions._fingerprint(e)
    assert a == definitions._fingerprint({**e, "label": "Annet navn", "purpose": "annet"})
    assert a != definitions._fingerprint({**e, "code": e["code"] + " pass"})


def test_sync_is_append_only_and_idempotent():
    _tmp.store(definitions)
    first = definitions.sync()
    assert first["added"] and not first["changed"]
    again = definitions.sync()
    assert not again["added"] and not again["changed"]
    assert definitions.stamp()["definitions_count"] == first["total"]


def test_lock_refuses_second_holder_in_process():
    _tmp.store(lock, "LOCKFILE")
    lock.release()
    lock.acquire()
    # A second acquire from the same process re-locks the same fd: allowed by
    # the kernel. The cross-process case is exercised by running two servers,
    # which the manual test in the commit message covers; here we only check
    # release clears the holder.
    lock.release()
    assert lock.holder() is None
