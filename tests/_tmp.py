"""Point a module's on-disk store, or the database, at a throwaway file."""
import tempfile
from pathlib import Path


def store(module, attr: str = "STORE") -> Path:
    path = Path(tempfile.mkdtemp()) / "store.json"
    setattr(module, attr, path)
    if hasattr(module, "_cache") and isinstance(module._cache, dict):
        module._cache.clear()
    return path


def db() -> Path:
    """A fresh, empty database for one test. Returns its path."""
    import db as database
    path = Path(tempfile.mkdtemp()) / "cfo.db"
    database.reset_for_tests(path)
    return path
