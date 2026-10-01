"""What each figure means — pinned, fingerprinted and versioned.

A KPI that quietly changes meaning is worse than one that is wrong, because a
wrong number gets argued with and a drifting one does not. If "lønnsandel"
counts 5000–5999 in March and 5000–5099 in April, the trend line says the
company improved. Nobody lied; the definition moved.

So every figure the product reports has an entry here stating what it means,
and a fingerprint taken over **both** the stated meaning and the source code
that computes it. That second half is what makes this a guardrail rather than
a comment: editing `_dso` without touching its description still moves the
fingerprint, and the change is recorded whether or not anyone meant to record
it. Definitions are append-only — a new version is added, the old one stays
readable, and figures stamped with it keep their meaning.

The ledger lives in `state/definitions.json` and is written at startup. The
first run records version 1 of everything; after that, only real changes.
"""
import hashlib
import inspect
import json
import logging
import os
import re
import tempfile
from datetime import date
from pathlib import Path

import calc
import config
import industry

log = logging.getLogger("cfo.definitions")

STORE = config.ROOT / "state" / "definitions.json"

# What each metric means, in words a person can check the code against. The
# wording is part of the fingerprint: changing the sentence is changing the
# definition, which is the point.
FORMULAS: dict[str, str] = {
    # calc.py — the arithmetic the agent is required to route through
    "share": "part ÷ whole × 100",
    "change": "(now − before) ÷ |before| × 100",
    "variance": "actual − budget, and that gap as a share of |budget|",
    "margin": "result ÷ revenue × 100",
    "wage_ratio": "wages ÷ revenue × 100, on total payroll cost",
    "dso": ("receivables ÷ (revenue × (1 + VAT)) × days; revenue is grossed up "
            f"at {calc.VAT_RATE:.2f} because receivables include VAT"),
    "annualise": "value ÷ days elapsed × 365",
    "per_head": "value ÷ FTE, where FTE is the sum of the employment percentages",
    "runway": "cash ÷ monthly cost",
    "accruing_tax": f"profit before tax × {calc.TAX_RATE:.2f}",
    "vat_gross": f"net × (1 + {calc.VAT_RATE:.2f})",
    "vat_net": f"gross ÷ (1 + {calc.VAT_RATE:.2f})",

    # industry.py — the figures the dashboard tracks month after month, which
    # is exactly where a silent change of meaning does its damage.
    "lonnsandel": "total payroll cost (5000–5999) ÷ operating revenue × 100",
    "driftsmargin": "operating result ÷ operating revenue × 100",
    "omsetning_per_ansatt": "revenue annualised ÷ FTE (sum of employment percentages ÷ 100)",
    "lonn_per_ansatt": "payroll cost annualised ÷ FTE (sum of employment percentages ÷ 100)",
    "resultat_per_ansatt": "operating result annualised ÷ FTE (sum of employment percentages ÷ 100)",
    "vekst": "revenue this year to date vs the same period last year, in per cent",
    "varekostandel": "cost of goods (4000–4999) ÷ revenue × 100",
    "bruttomargin": "(revenue − cost of goods) ÷ revenue × 100",
    "andre_kostnader": "other operating cost (6000–7999) ÷ revenue × 100",
    "betalingstid": "the dso definition above, applied to the ledger's figures",
    "storste_kunde": "largest single customer's revenue ÷ total revenue × 100",
    "topp_tre": "three largest customers' revenue ÷ total revenue × 100",
    "frie_penger": ("bank balance less everything already committed, as "
                    "commitments.py dates it"),
    "kontantdager": "free cash ÷ average daily operating cost",
    "likviditetsgrad": "Tripletex Likviditetsgrad 1, read from Nøkkeltallsrapport",
    "egenkapitalandel": ("(assets 1000–1999 − debt 2100–2999) ÷ assets × 100, "
                         "computed from the trial balance; Tripletex's own "
                         "Egenkapitalandel row reports 0 and is not used"),
}

_COMMENT = re.compile(r"#.*$", re.MULTILINE)
_SPACE = re.compile(r"\s+")


def _source_of(fn) -> str:
    """The implementation, normalised so comments and layout do not churn
    versions — only what the code actually does."""
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return "<source unavailable>"
    return _SPACE.sub(" ", _COMMENT.sub("", src)).strip()


def _entries() -> dict[str, dict]:
    """Every definition currently in force, gathered from the code itself."""
    out: dict[str, dict] = {}
    for name, (fn, args, desc) in calc.METRICS.items():
        out[name] = {"id": name, "source": "calc", "label": name,
                     "inputs": args, "unit": "", "purpose": desc,
                     "formula": FORMULAS.get(name, "(udokumentert)"),
                     "code": _source_of(fn)}
    for kpi in industry.CATALOGUE:
        out[kpi.id] = {"id": kpi.id, "source": "industry", "label": kpi.label,
                       "inputs": "", "unit": kpi.unit, "purpose": kpi.plain,
                       "formula": FORMULAS.get(kpi.id, "(udokumentert)"),
                       "code": _source_of(kpi.compute)}
    return out


def _fingerprint(entry: dict) -> str:
    """Hash of the meaning and the implementation together.

    Label and purpose are left out on purpose: rewording a description for the
    CEO is not a change of definition, and versioning it would train everyone
    to ignore the version.
    """
    payload = {k: entry[k] for k in ("formula", "inputs", "unit", "code")}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------- the ledger

def _load() -> dict:
    if not STORE.exists():
        return {"definitions": {}}
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        # A definitions ledger must never be silently discarded: it is the
        # record of what past figures meant. Keep it and refuse to overwrite.
        log.error("Definisjonsloggen er ulesbar (%s). Den blir stående urørt; "
                  "versjonering er av til noen ser på den.", exc)
        raise
    data.setdefault("definitions", {})
    return data


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STORE.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def sync(note: str = "") -> dict:
    """Record any definition that has changed since last time.

    Append-only. A changed formula or a changed implementation becomes a new
    version; the previous one stays in the file so a figure stamped with it can
    still be read correctly a year from now.
    """
    current = _entries()
    data = _load()
    ledger = data["definitions"]
    today = date.today().isoformat()

    added, changed = [], []
    for kid, entry in sorted(current.items()):
        fp = _fingerprint(entry)
        history = ledger.setdefault(kid, [])
        if history and history[-1]["fingerprint"] == fp:
            continue
        version = len(history) + 1
        seen = next((h["version"] for h in history if h["fingerprint"] == fp), None)
        history.append({
            "version": version, "fingerprint": fp, "recorded": today,
            "source": entry["source"], "label": entry["label"],
            "formula": entry["formula"], "inputs": entry["inputs"],
            "unit": entry["unit"], "code": entry["code"],
            "note": note or ("første registrering" if version == 1
                             else f"tilbake til v{seen}" if seen
                             else "endret definisjon"),
        })
        (added if version == 1 else changed).append(kid)

    retired = sorted(set(ledger) - set(current))
    if added or changed:
        data["updated"] = today
        _save(data)
    if changed:
        log.warning("Definisjoner endret (%d): %s — nye versjoner er lagret, "
                    "tidligere tall beholder sin gamle betydning",
                    len(changed), ", ".join(changed))
    if retired:
        log.warning("Definisjoner finnes i loggen, men ikke lenger i koden: %s",
                    ", ".join(retired))
    return {"added": added, "changed": changed, "retired": retired,
            "total": len(current)}


def registry() -> dict:
    """Every definition's history, keyed by id."""
    return _load()["definitions"]


def versions() -> dict[str, int]:
    """Current version of every definition, for stamping onto figures."""
    try:
        ledger = _load()["definitions"]
    except Exception:  # noqa: BLE001
        return {}
    return {k: h[-1]["version"] for k, h in ledger.items() if h}


def stamp() -> dict:
    """A compact mark to store with any figure we keep over time.

    One hash over every definition in force, so a snapshot taken today can be
    told apart from one taken under different rules — without copying thirty
    version numbers into every row.
    """
    v = versions()
    blob = json.dumps(v, sort_keys=True)
    return {"definitions_hash": hashlib.sha256(blob.encode()).hexdigest()[:10],
            "definitions_version": sum(v.values()) if v else 0,
            "definitions_count": len(v)}


def history(kid: str) -> list[dict]:
    try:
        return _load()["definitions"].get(kid, [])
    except Exception:  # noqa: BLE001
        return []


def briefing() -> str:
    """The definitions block for the system prompt."""
    try:
        ledger = _load()["definitions"]
    except Exception:  # noqa: BLE001
        return ""
    if not ledger:
        return ""
    rows = []
    for kid, hist in sorted(ledger.items()):
        h = hist[-1]
        mark = f" (v{h['version']}, endret {h['recorded']})" if h["version"] > 1 else ""
        rows.append(f"- **{h['label']}** — {h['formula']}{mark}")
    return (
        "## Hvordan tallene er definert\n\n"
        "These are the definitions in force. They are fixed, versioned and "
        "recorded; a figure means what it says here and nothing else. Do not "
        "compute a KPI a different way because another way seems better in "
        "this particular case — a measure that changes shape between months "
        "destroys the only thing a trend is good for. If a definition is wrong, "
        "say so plainly and keep reporting the current one until it is changed "
        "deliberately.\n\n"
        + "\n".join(rows)
        + "\n\nWhere a definition shows a version above 1, it changed on the "
          "date given. Figures from before that date were measured the old way "
          "— say so if you compare across the change.")
