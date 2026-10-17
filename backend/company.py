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
COMPANY_FILE = config.STATE / "company.md"
TEMPLATE = config.ROOT / "company.md"        # seeded on first use, then ignored
MAX_CHARS = 20_000
KEEP_VERSIONS = 10

# Only these are read by code, and all but AGENT_ONLY in arithmetic. Anything
# else in the block is passed to the agent as a stated fact but changes no
# arithmetic — said plainly so nobody expects a number to move because they
# wrote a line here.
KNOWN = {
    "lonn_etterskuddsvis_mnd": ("int", "hvor mange måneder etter arbeidet "
                                "lønnen utbetales; Arvaka leser månedstallene "
                                "med det, men det flytter ingen tall"),
    "lonn_utbetalingsdag": ("int", "dag i måneden lønnen kjøres (1–31)"),
    "kredittid_dager": ("int", "standard betalingsfrist på fakturaene deres; "
                        "prognosen bruker den når fakturaene ikke viser "
                        "betalingstiden selv"),
    "ferie_utbetalingsmnd": ("int", "måneden feriepengene utbetales (1-12)"),
    "ferie_uker": ("int", "hvor mange uker ferie de ansatte har"),
    # The rulebook: thresholds every card, alert and brief is measured against.
    "likviditetsgulv_kr": ("kr", "laveste saldo dere vil ha på konto; under "
                           "den varsler Arvaka"),
    "purring_etter_dager": ("int", "dager etter forfall før en kunde purres"),
    "varsel_minimum_kr": ("kr", "beløp under dette gir ingen sak eller varsel"),
    "lonnsandel_mal_pct": ("pct", "målet for lønn som andel av omsetningen, "
                           "i prosent"),
    "kostnadsavvik_pct": ("pct", "hvor mye over sitt vanlige nivå en "
                          "kostnadskonto må ligge en måned før Arvaka sier "
                          "fra, i prosent"),
    "brev_mottakere": ("emails", "hvem mandagsbrevet sendes til på e-post, "
                       "skilt med komma; står den ikke, går det til den som "
                       "logger inn"),
}

# Read by the CFO to explain the figures, never in a calculation. The page that
# lists the settings must not say they move numbers.
AGENT_ONLY = {"lonn_etterskuddsvis_mnd"}

# The company's own rules. They decide when a card is raised and what the
# brief calls tight, so they are settings the engine reads — a "2 MNOK floor"
# written in the prose is a sentence the agent might read one way today and
# another tomorrow. A rule nobody set still has to be *something*, because a
# card is raised under some floor, so each has a default, and whatever uses one
# says when it is ours rather than theirs.
RULES = ("likviditetsgulv_kr", "purring_etter_dager", "varsel_minimum_kr",
         "lonnsandel_mal_pct", "kostnadsavvik_pct")
RULE_DEFAULTS = {
    "purring_etter_dager": 14,
    "varsel_minimum_kr": 10_000,
    # No target is better than one we made up: a payroll share is only "too
    # high" against a number someone in the company chose.
    "lonnsandel_mal_pct": None,
    # A cost account half again above its usual month is worth a look; less
    # than that is ordinary month-to-month noise in a small company.
    "kostnadsavvik_pct": 50,
}
# The floor defaults to one month's wages, which is what the Brief has always
# drawn: whether the account covers the next payroll. This is only for when the
# forecast has no wage figure to give.
FLOOR_FALLBACK = 500_000

MONTH_NAMES = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
               "august", "september", "oktober", "november", "desember"]

_cache: dict = {}


def _kroner(raw: str) -> int | None:
    """An amount as people write it: «2 000 000», «2000000 kr», «2 MNOK», «20k».

    Anything else is refused rather than guessed at. Picking the first digits
    out of «2 000 000», as the plain number reader does, would set a floor of
    two kroner and silence every cash alert without anyone noticing.
    """
    s = raw.lower().replace(" ", " ").replace(" ", " ").strip()
    s = re.sub(r"^(kr\.?|nok)\s*", "", s)
    s = re.sub(r"\s*(kr\.?|nok|,-)$", "", s).strip()
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(mnok|mill\.?|millioner|million|m|k|tusen)", s)
    if m:
        scale = 1_000 if m.group(2) in ("k", "tusen") else 1_000_000
        return round(float(m.group(1).replace(",", ".")) * scale)
    if re.fullmatch(r"\d{1,3}(?:[ .]\d{3})+|\d+", s):
        return int(re.sub(r"[ .]", "", s))
    return None


def _percent(raw: str) -> int | float | None:
    """«75», «75 %» or «72,5». A share above 100 or at zero is a typo."""
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*%?\s*", raw)
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    if not 0 < value <= 100:
        return None
    return int(value) if value.is_integer() else value


EMAIL = re.compile(r"[^@\s,;<>]+@[^@\s,;<>]+\.[a-z]{2,}", re.IGNORECASE)


def _emails(raw: str) -> tuple[list[str], list[str]]:
    """Addresses split on commas, semicolons or spaces: (good, refused)."""
    good, bad = [], []
    for part in re.split(r"[,;\s]+", raw.strip()):
        if not part:
            continue
        if EMAIL.fullmatch(part):
            if part.lower() not in good:
                good.append(part.lower())
        else:
            bad.append(part)
    return good, bad


_WHAT = {"kr": "et kronebeløp, som 2 000 000 eller 2 MNOK",
         "pct": "en prosent over 0 og opptil 100, som 75"}


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
            if key in RULES and int(m.group()) < 0:
                notes.append(f"«{key}» kan ikke være negativ. «{raw}» ble "
                             f"hoppet over, og beregningene bruker "
                             f"standardverdien.")
                continue
            settings[key] = int(m.group())
        elif kind == "emails":
            good, bad = _emails(raw)
            if bad:
                notes.append(f"«{key}»: {', '.join(f'«{b}»' for b in bad)} er "
                             f"ikke en e-postadresse og ble hoppet over.")
            if good:
                settings[key] = good
        elif kind in _WHAT:
            value = _kroner(raw) if kind == "kr" else _percent(raw)
            if value is None:
                notes.append(f"«{key}» må være {_WHAT[kind]}. «{raw}» ble "
                             f"hoppet over, og beregningene bruker "
                             f"standardverdien.")
                continue
            settings[key] = value
        else:
            settings[key] = raw
            if key not in KNOWN:
                notes.append(f"«{key}» kjenner ikke beregningene til. Den blir "
                             f"fortalt til Arvaka som et faktum, men flytter "
                             f"ingen tall.")
    return settings, story.lstrip("\n"), notes


def _seed() -> None:
    """First run: copy the starter in, so the editor opens on prompts rather
    than an empty box. Nobody writes a company description into a blank page."""
    if COMPANY_FILE.exists() or not TEMPLATE.exists() or config.DEMO:
        # A demo company brings its own description (demo/companies.py);
        # the template is the real customer's.
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


def rules(monthly_wages: float | None = None) -> dict[str, dict]:
    """Each rule as the calculations will use it, and where it came from.

    `assumed` is true when the value is ours, not the company's — that is what
    lets the brief say "gulvet er antatt" instead of presenting our guess as
    their rule. `monthly_wages` is the forecast's, for the floor's default;
    without it the floor falls back to FLOOR_FALLBACK.
    """
    settings = load()["settings"]
    wages = round(monthly_wages) if monthly_wages and monthly_wages > 0 else None
    out: dict[str, dict] = {}
    for key in RULES:
        if key in settings:
            value, basis, assumed = settings[key], "company.md", False
        elif key == "likviditetsgulv_kr":
            value, basis = ((wages, "én månedslønn") if wages
                            else (FLOOR_FALLBACK, "standard"))
            assumed = True
        else:
            value = RULE_DEFAULTS[key]
            basis = "standard" if value is not None else "ikke satt"
            assumed = value is not None
        out[key] = {"value": value, "assumed": assumed, "basis": basis,
                    "label": KNOWN[key][1]}
    return out


def recipients() -> list[str]:
    """Who the Monday brief is emailed to: the rulebook's list, or else
    whoever may sign in."""
    return list(setting("brev_mottakere") or sorted(config.OWNER_EMAILS))


def said(rule: dict) -> str:
    """Where a rule came from, in the words the CEO reads."""
    if not rule["assumed"]:
        return "satt i Selskapet" if rule["value"] is not None else "ikke satt"
    basis = "standardverdi" if rule["basis"] == "standard" else rule["basis"]
    return f"antatt: {basis} — ikke satt i Selskapet"


def _rules_briefing() -> str:
    """The rulebook, for the agent. No figures from the forecast here: this
    sits in the cached block, and the floor's amount is said with the forecast."""
    r = rules()
    floor, days = r["likviditetsgulv_kr"], r["purring_etter_dager"]
    alert, wage = r["varsel_minimum_kr"], r["lonnsandel_mal_pct"]
    out = ["### Selskapets regler\n",
           "Thresholds the cards, the alerts and the brief are measured "
           "against. Use these, never a rule of thumb of your own. When one is "
           "assumed rather than set by the company, say so whenever you rely "
           "on it, and that the CEO can set his own under Selskapet.\n"]
    out.append(f"- Likviditetsgulv: " + (
        f"{_kr(floor['value'])} kr, satt i Selskapet." if not floor["assumed"]
        else "ikke satt — antatt én månedslønn. Beløpet står med prognosen."))
    out.append(f"- Purring: når en kunde er {days['value']} dager forbi "
               f"forfall ({said(days)}).")
    out.append(f"- Varsel: ingen sak eller varsel under {_kr(alert['value'])} "
               f"kr ({said(alert)}).")
    out.append(f"- Lønnsandel: mål {wage['value']} % ({said(wage)})."
               if wage["value"] is not None else
               "- Lønnsandel: ikke noe mål satt. Ikke kall en lønnsandel for "
               "høy eller lav mot et mål selskapet ikke har valgt; sammenlign "
               "med budsjettet eller med tidligere måneder i stedet.")
    return "\n".join(out) + "\n"


def _kr(v) -> str:
    return f"{round(v):,}".replace(",", " ")


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
    ferie_month = data["settings"].get("ferie_utbetalingsmnd")
    ferie_weeks = data["settings"].get("ferie_uker")
    if ferie_month or ferie_weeks:
        # Both change which week of the forecast is the tight one, so the
        # agent is told them in the same breath as the pay day.
        said = []
        if ferie_month:
            said.append(f"feriepengene utbetales i {MONTH_NAMES[ferie_month - 1]}"
                        if 1 <= int(ferie_month) <= 12 else "")
        if ferie_weeks:
            said.append(f"de ansatte har {ferie_weeks} uker ferie")
        said = [s for s in said if s]
        if said:
            out.append(f"{' og '.join(said).capitalize()}. I den måneden tar de "
                       f"ansatte ut feriepenger i stedet for vanlig lønn, så "
                       f"lønnen den måneden er lavere eller faller bort.\n")
    out.append(_rules_briefing())
    if data["story"]:
        out.append(data["story"])
    return "\n".join(out)
