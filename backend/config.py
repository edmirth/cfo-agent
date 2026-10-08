"""Runtime configuration, read once from the environment."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# Satt av scripts/oauth_login.py — en engangsinnlogging i nettleseren.
TRIPLETEX_CLIENT_ID = os.getenv("TRIPLETEX_CLIENT_ID") or ""
TRIPLETEX_REFRESH_TOKEN = os.getenv("TRIPLETEX_REFRESH_TOKEN") or ""
TRIPLETEX_MCP_URL = os.getenv("TRIPLETEX_MCP_URL", "https://mcp.tripletex.no")
COMPANY_NAME = os.getenv("COMPANY_NAME", "Selskapet")

CFO_MODEL = os.getenv("CFO_MODEL", "claude-opus-5")
CFO_EFFORT = os.getenv("CFO_EFFORT", "high")

# The agent definition is the single source of truth for the CFO's behaviour.
# Claude Code reads this same file as a subagent; the web app reads it here.
AGENT_DEFINITION = ROOT / ".claude" / "agents" / "cfo.md"

MAX_TOKENS = 64_000
# Conversations are pruned to this many messages before each request so a long
# session cannot grow without bound. Compaction handles the rest server-side.
MAX_HISTORY_MESSAGES = 60
# Ceiling on tool rounds in a single turn, so a loop cannot run away.
MAX_TOOL_ROUNDS = 12

# What runs without anyone asking (backend/scheduler.py). CFO_SCHEDULER=off
# stops it, for a server that should not spend a model call of its own.
SCHEDULER = os.getenv("CFO_SCHEDULER", "on").strip().lower() not in ("off", "0", "false", "no")
# The company's clock, whatever the machine's: a host in UTC still runs the
# morning at seven in Norway.
TIMEZONE = os.getenv("CFO_TIMEZONE", "Europe/Oslo")
MORNING_AT = os.getenv("CFO_MORNING_AT", "07:00")
