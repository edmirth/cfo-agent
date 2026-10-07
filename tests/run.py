"""Run every check in this directory, without pytest.

    ./.venv/bin/python -m tests.run

Each test_*.py module exposes functions named test_*; each is run in turn,
against temporary state so nothing here touches the live company's files.
Plain asserts, no framework: the venv has none, and adding a dependency so
that the tests can exist would be the wrong trade.
"""
import importlib
import os
import pkgutil
import sys
import tempfile
import traceback
from pathlib import Path

# Before any backend module is imported: the whole run writes to a throwaway
# database, so no test can reach state/cfo.db or import the real JSON files.
os.environ["CFO_DB"] = str(Path(tempfile.mkdtemp()) / "cfo.db")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
sys.path.insert(0, str(HERE.parent))


def main() -> int:
    failed = 0
    total = 0
    for info in sorted(pkgutil.iter_modules([str(HERE)]), key=lambda i: i.name):
        if not info.name.startswith("test_"):
            continue
        module = importlib.import_module(f"tests.{info.name}")
        for name in sorted(dir(module)):
            if not name.startswith("test_"):
                continue
            total += 1
            try:
                getattr(module, name)()
                print(f"  ok    {info.name}.{name}")
            except Exception:  # noqa: BLE001 — report every failure, stop for none
                failed += 1
                print(f"  FAIL  {info.name}.{name}")
                traceback.print_exc(limit=3)
    print(f"\n{total - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
