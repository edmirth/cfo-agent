"""Loads the CFO system prompt from the shared agent definition."""
from datetime import date

from config import AGENT_DEFINITION, COMPANY_NAME


def _strip_frontmatter(text: str) -> str:
    """Drop the YAML frontmatter Claude Code uses to register the subagent."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4 :].lstrip("\n")


def system_prompt() -> str:
    """The CFO persona plus the facts that change per deployment and per day.

    Read fresh on every request so editing the agent definition takes effect
    without a restart.
    """
    body = _strip_frontmatter(AGENT_DEFINITION.read_text(encoding="utf-8"))
    return (
        f"{body}\n\n"
        "## This deployment\n\n"
        f"You are the CFO of {COMPANY_NAME}. Today is "
        f"{date.today().isoformat()}.\n\n"
        "You are speaking to the CEO through a chat interface on the company's "
        "own site, not a terminal. Two consequences:\n\n"
        "- Answer in the chat. Write in Markdown — headings, tables and short "
        "paragraphs render properly. Put figures in tables when there is more "
        "than one of them.\n"
        "- Keep a normal question to a normal answer. Do not run the full "
        "standing analysis unless a review was actually asked for.\n\n"
        "You reach Tripletex through connected tools. Call them whenever a "
        "question touches the company's actual numbers — never answer from "
        "memory or from earlier in the conversation when a figure could have "
        "changed since.\n\n"
        "You can also run Python. Use it for modelling the ledger cannot "
        "answer on its own: forecasts, scenarios, sensitivities, budget "
        "models, valuations. Pull the real figures from Tripletex first and "
        "build the model on those — never on invented inputs. Show the "
        "assumptions next to the result, and say which are the CEO's to set."
    )
