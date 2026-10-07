"""Chat history, kept in the database instead of the server's memory.

A conversation is keyed by the `session_id` the browser already sends, and
holds its messages in order, each one's content blocks exactly as the
Anthropic API takes them — `thinking`, `tool_use` and `tool_result` included —
so a conversation reloads as it was, after a restart or on another worker.

A turn is written when it finishes, in one transaction: the question and every
message the answer produced. An interrupted or failed turn writes nothing,
which is the rollback the agent core already does on the history in memory.

Trimming to `MAX_HISTORY_MESSAGES` happens on reading, so nothing is deleted
to make a conversation fit. Deleting a conversation is the one delete, and
only the owner asks for it, from the conversation list.
"""
import logging

import config
import db

log = logging.getLogger("cfo.conversations")

TITLE_CHARS = 80


def _plain(block):
    """A content block as JSON, the shape the API sent and takes back.

    SDK blocks dump with only the fields the API set (`to_dict` leaves out
    unset ones), which keeps a thinking block's signature and every id exactly
    as they came.
    """
    if isinstance(block, dict):
        return block
    if hasattr(block, "to_dict"):
        return block.to_dict(mode="json")
    raise TypeError(f"Kan ikke lagre innhold av typen {type(block).__name__}")


def _content(content):
    return content if isinstance(content, str) else [_plain(b) for b in content]


def answers_a_tool(msg: dict) -> bool:
    """True when this user message only carries tool results."""
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any((b.get("type") if isinstance(b, dict) else getattr(b, "type", None))
               == "tool_result" for b in content)


def load(session_id: str, limit: int = config.MAX_HISTORY_MESSAGES) -> list[dict]:
    """The latest messages of a conversation, ready to send to the model.

    Cut to `limit`, and then to open on a real question: an assistant turn, or
    a user turn carrying tool results whose tool_use was cut away, is rejected
    by the API.
    """
    with db.read() as conn:
        rows = conn.execute(
            "SELECT role, content FROM ("
            "  SELECT seq, role, content FROM messages"
            "  WHERE company_id = ? AND conversation_id = ?"
            "  ORDER BY seq DESC LIMIT ?) ORDER BY seq",
            (db.company_id(), session_id, limit)).fetchall()
    history = [{"role": r["role"], "content": db.loads(r["content"])} for r in rows]
    while history and (history[0]["role"] != "user" or answers_a_tool(history[0])):
        history.pop(0)
    return history


def append(session_id: str, messages: list[dict],
           job_run_id: int | None = None) -> None:
    """Add a finished turn's messages, all or none, with the run that made
    them. The run is passed in: by the time a turn is saved its run is over."""
    if not messages:
        return
    cid, now, run = db.company_id(), db.now(), job_run_id
    first = next((m["content"] for m in messages
                  if m["role"] == "user" and isinstance(m["content"], str)), "")
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO conversations (id, company_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET "
            "updated_at = excluded.updated_at",
            (session_id, cid, first[:TITLE_CHARS] or None, now, now))
        seq = conn.execute("SELECT coalesce(max(seq), 0) FROM messages "
                           "WHERE conversation_id = ?", (session_id,)).fetchone()[0]
        for i, m in enumerate(messages, start=1):
            conn.execute(
                "INSERT INTO messages (company_id, conversation_id, seq, role, "
                "content, created_at, job_run_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, session_id, seq + i, m["role"],
                 db.dumps(_content(m["content"])), now, run))


def delete(session_id: str) -> None:
    """Forget a conversation the owner deleted."""
    with db.tx() as conn:
        conn.execute("DELETE FROM conversations WHERE company_id = ? AND id = ?",
                     (db.company_id(), session_id))
