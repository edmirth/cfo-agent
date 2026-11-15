"""The data map: where a company's numbers are, and what they mean.

It never holds amounts. It says which accounts play which role, which VAT a
revenue account carries, which suppliers are fixed costs, which months were
one-offs, and the code reads the amounts from the books itself. The system
writes it (card 71) and runs it without asking anyone: an entry counts only
when its `check` is "verified", meaning the books confirm it. One the books
contradict, or that could not be checked, is kept for the record and changes
nothing, so the forecast keeps its measured or default value.

Format, schema 1 (`state/data_maps/<company id>.json`):

    {
      "schema": 1,
      "version": 3,                      # increases with every new map
      "made": "2026-11-15",
      "made_by": "hand" | {"model": "...", "prompt": "..."},
      "accounts": {
        "receivables": {"accounts": [[1500, 1509], 1530],
                        "check": "verified", "why": "1530 holds factoring"}
      },
      ...                                # revenue, vat_term, payroll, fixed
    }                                    # suppliers etc.: card 70 steps 3-4

Accounts are given as a number or a [first, last] range.
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import config

log = logging.getLogger("cfo.datamap")

SCHEMA = 1
CHECKS = ("verified", "contradicted", "unchecked")
DIR = config.STATE / "data_maps"


@dataclass(frozen=True)
class Entry:
    value: Any
    check: str
    why: str | None = None


@dataclass(frozen=True)
class DataMap:
    version: int
    made: str | None
    made_by: Any
    accounts: dict[str, Entry]
    raw: dict = field(compare=False)      # the parts later steps read
    problems: tuple[str, ...] = ()


def _ranges(value: Any) -> tuple[tuple[int, int], ...] | None:
    """[[1500, 1509], 1530] as ((1500, 1509), (1530, 1530)), or None."""
    if not isinstance(value, list) or not value:
        return None
    out = []
    for item in value:
        if isinstance(item, int) and 1000 <= item <= 9999:
            out.append((item, item))
        elif (isinstance(item, list) and len(item) == 2
              and all(isinstance(n, int) and 1000 <= n <= 9999 for n in item)
              and item[0] <= item[1]):
            out.append((item[0], item[1]))
        else:
            return None
    return tuple(out)


def parse(raw: Any) -> DataMap | None:
    """A data map from its JSON, with a reason for everything left out.
    None if it is not a data map of a schema this code reads."""
    import chart
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return None
    problems: list[str] = []
    accounts: dict[str, Entry] = {}
    for role, entry in (raw.get("accounts") or {}).items():
        if role not in chart.ACCOUNT_ROLES:
            problems.append(f"accounts.{role}: no such role")
            continue
        if not isinstance(entry, dict):
            problems.append(f"accounts.{role}: not an entry")
            continue
        ranges = _ranges(entry.get("accounts"))
        check = entry.get("check")
        if ranges is None:
            problems.append(f"accounts.{role}: accounts must be numbers or [first, last]")
            continue
        if check not in CHECKS:
            problems.append(f"accounts.{role}: check must be one of {', '.join(CHECKS)}")
            continue
        accounts[role] = Entry(ranges, check, entry.get("why"))
    version = raw.get("version")
    return DataMap(version=version if isinstance(version, int) else 0,
                   made=raw.get("made"), made_by=raw.get("made_by"),
                   accounts=accounts, raw=raw, problems=tuple(problems))


def path(company_id: Any) -> Path:
    return DIR / f"{company_id}.json"


def load(company_id: Any = None) -> DataMap | None:
    """The company's current data map, or None if it has none or it cannot
    be read; a map that cannot be read is said in the log and ignored."""
    if not DIR.exists():
        return None
    if company_id is None:
        import db
        company_id = db.company_id()
    p = path(company_id)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Datakartet for %s kunne ikke leses: %s", company_id, exc)
        return None
    m = parse(raw)
    if m is None:
        log.warning("Datakartet for %s har et skjema denne koden ikke leser", company_id)
        return None
    for problem in m.problems:
        log.info("Datakartet for %s: %s", company_id, problem)
    return m
