"""What every test run needs before a backend module is imported, shared by
the plain runner (`python -m tests.run`) and pytest (`conftest.py`)."""
import os
import sys
import tempfile
from pathlib import Path

# The whole run writes to a throwaway database, so no test can reach
# state/cfo.db or import the real JSON files.
os.environ["CFO_DB"] = str(Path(tempfile.mkdtemp()) / "cfo.db")
# Login switched on, against a project that does not exist: the routes the
# tests call directly are not behind it, and the auth tests set their own keys.
os.environ["CFO_AUTH"] = "supabase"
os.environ["SUPABASE_URL"] = "https://test-project.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "test-anon-key"
os.environ["CFO_OWNER_EMAIL"] = "ceo@example.no"

HERE = Path(__file__).resolve().parent
for path in (HERE.parent, HERE.parent / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
