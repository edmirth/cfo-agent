"""Point a module's on-disk store at a throwaway file for one test."""
import tempfile
from pathlib import Path


def store(module, attr: str = "STORE") -> Path:
    path = Path(tempfile.mkdtemp()) / "store.json"
    setattr(module, attr, path)
    if hasattr(module, "_cache") and isinstance(module._cache, dict):
        module._cache.clear()
    return path
