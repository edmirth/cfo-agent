"""How this particular company works, in its own words.

The ledger says what happened. It does not say that wages are paid a month in
arrears, that the busy season is spring, that one customer always pays late but
always pays, or that the owner draws no salary. Those facts change what the
numbers mean, and without them an agent reads a perfectly normal month as a
crisis — September's payroll set against September's revenue looks like a
collapse in margin, when it is August's work being paid for.

`company.md` at the root is where that gets written, by a human, in prose. Two
parts:

- a short block of settings at the top, for the handful of facts the
  *calculations* need — a date cannot be inferred from a paragraph;
- everything below it, free text, handed to the agent as written.

Kept deliberately simple to edit. No YAML parser, no schema to learn: `key:
value` lines between two `---` markers, and prose underneath. A file that is
awkward to edit does not get updated, and a company description nobody updates
is worse than none, because it is believed.
"""
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger("cfo.company")

# Client data, not code. It lives with the rest of this customer's state so
# that deploying the product never ships one company's story to another, and
# so the people who run the business can edit it in the app instead of asking
# someone to change a file in a repository.
COMPANY_FILE = config.ROOT / "state" / "company.md"
TEMPLATE = config.ROOT / "company.md"        # seeded on first use, then ignored
MAX_CHARS = 20_000
KEEP_VERSIONS = 10

# Only these are read by code. Anything else in the block is passed to the
# agent as a stated fact but changes no arithmetic — said plainly so nobody
# expects a number to move because they wrote a line here.
KNOWN = {
    "lonn_etterskuddsvis_mnd": ("int", "hvor mange måneder etter arbeidet "
                                "lønnen utbetales"),
    "lonn_utbetalingsdag": ("int", "dag i måneden lønnen kjøres (1–31)"),
    "kredittid_dager": ("int", "standard betalingsfrist på fakturaene deres"),
}

_cache: dict = {}


def _parse(text: str) -> tuple[dict, str, list[str]]:
    """Split the settings block from the prose, and say what was ignored."""
    notes: list[str] = []
    if not text.startswith("---"):
        return {}, text, notes
    end = text.find("\n---", 3)
    if end == -1:
        notes.append("Innstillingsblokken øverst er ikke lukket med en linje "
                     "som bare inneholder ---. Ingen innstillinger ble lest.")
        return {}, text, notes
    block, story = text[3:end], text[end + 4:]
    settings: dict = {}
    for line in block.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key, raw = key.strip(), raw.strip()
        if not key:
            continue
        kind = KNOWN.get(key, (None,))[0]
        if kind == "int":
            m = re.search(r"-?\d+", raw)
            if m is None:
                notes.append(f"«{key}» må være et tall. «{raw}» ble hoppet "
                             f"over, og beregningene bruker den ikke.")
                continue
            settings[key] = int(m.group())
        else:
            settings[key] = raw
            if key not in KNOWN:
                notes.append(f"«{key}» kjenner ikke beregningene til. Den blir "
                             f"fortalt til CFO-en som et faktum, men flytter "
                             f"ingen tall.")
    return settings, story.lstrip("\n"), notes


def _seed() -> None:
    """First run: copy the starter in, so the editor opens on prompts rather
    than an empty box. Nobody writes a company description into a blank page."""
    if COMPANY_FILE.exists() or not TEMPLATE.exists():
        return
    try:
        COMPANY_FILE.parent.mkdir(parents=True, exist_ok=True)
        COMPANY_FILE.write_text(TEMPLATE.read_text(encoding="utf-8"),
                                encoding="utf-8")
        log.info("Opprettet state/company.md fra malen")
    except OSError as exc:
        log.error("Kunne ikke opprette company.md: %s", exc)


def raw() -> str:
    _seed()
    try:
        return COMPANY_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""


def save(text: str) -> dict:
    """Store what the client wrote, keeping the version it replaces.

    This is the only thing in the product a customer has written by hand. An
    accidental paste over it should be recoverable, so the previous text is
    kept rather than overwritten.
    """
    if len(text) > MAX_CHARS:
        raise ValueError(f"Teksten er for lang ({len(text)} tegn, maks {MAX_CHARS}).")
    COMPANY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if COMPANY_FILE.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            (COMPANY_FILE.parent / f"company.{stamp}.md").write_text(
                COMPANY_FILE.read_text(encoding="utf-8"), encoding="utf-8")
            old = sorted(COMPANY_FILE.parent.glob("company.*-*.md"))
            for stale in old[:-KEEP_VERSIONS]:
                stale.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Kunne ikke ta vare på forrige versjon: %s", exc)

    fd, tmp = tempfile.mkstemp(dir=COMPANY_FILE.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, COMPANY_FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _cache.clear()
    data = load(force=True)
    log.info("company.md lagret (%d tegn, %d innstillinger)",
             len(text), len(data["settings"]))
    return data


def load(force: bool = False) -> dict:
    """Read the file. Cheap enough to re-read; mtime keeps it honest."""
    _seed()
    if not COMPANY_FILE.exists():
        return {"settings": {}, "story": "", "exists": False, "notes": []}
    try:
        stamp = COMPANY_FILE.stat().st_mtime
    except OSError:
        stamp = 0
    if not force and _cache.get("stamp") == stamp:
        return _cache["data"]
    try:
        settings, story, notes = _parse(COMPANY_FILE.read_text(encoding="utf-8"))
    except OSError as exc:
        log.error("Kunne ikke lese company.md: %s", exc)
        return {"settings": {}, "story": "", "exists": False, "notes": []}
    for n in notes:
        log.info("company.md: %s", n)
    data = {"settings": settings, "story": story.strip(), "exists": True,
            "notes": notes}
    _cache.update({"stamp": stamp, "data": data})
    return data


def setting(key: str, default=None):
    return load()["settings"].get(key, default)


def briefing() -> str:
    """The company's own account of itself, for the system prompt."""
    data = load()
    if not data["exists"] or not (data["story"] or data["settings"]):
        return ""

    out = ["## Slik fungerer dette selskapet\n",
           "Written by the people who run it, not derived from the ledger. "
           "It tells you what the figures cannot: why a month looks the way it "
           "does. Trust it for how the business works and never for what a "
           "number is — if it contradicts the ledger, the ledger wins on "
           "figures and this wins on meaning, and a contradiction worth "
           "noticing is worth saying out loud.\n"]

    lag = data["settings"].get("lonn_etterskuddsvis_mnd")
    if lag:
        month = "måned" if lag == 1 else "måneder"
        out.append(
            f"**Lønn utbetales {lag} {month} etterskuddsvis.** Lønnen som "
            f"føres i en måned gjelder arbeid utført {lag} {month} tidligere. "
            f"Det betyr at lønnsandel og margin regnet innenfor én måned "
            f"sammenligner arbeidskraft med feil måneds omsetning. Si det når "
            f"du bruker et månedstall, og bruk heller hittil-i-år eller "
            f"forskjøvne måneder når spørsmålet er om lønnsomhet.\n")
    if data["settings"].get("lonn_utbetalingsdag"):
        out.append(f"Lønn kjøres den {data['settings']['lonn_utbetalingsdag']}. "
                   f"i måneden.\n")
    if data["settings"].get("kredittid_dager"):
        out.append(f"Standard betalingsfrist er "
                   f"{data['settings']['kredittid_dager']} dager.\n")
    if data["story"]:
        out.append(data["story"])
    return "\n".join(out)
