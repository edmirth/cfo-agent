"""Do the numbers in the answer come from anywhere?

The previous guardrail gave the agent calculators and told it to use them.
This one checks that it did. Every figure in a reply should be traceable to
something the agent was actually given: a Tripletex tool result, a figure this
server computed and put in the prompt, a value returned by `calculate` or
`metric`, or a number the CEO typed himself. A figure that matches none of
those was produced by the model, and a produced figure is exactly the one that
should never reach a CEO.

This reports; it does not block. A reply is not withheld because one number
looks unfamiliar — the cost of a false alarm mid-answer is higher than the
cost of a flag in a log that someone reads. What it does is make the failure
*visible*, which it currently is not.

Matching is deliberately tight. A figure counts as supported only if it equals
one the agent was given, allowing for rounding — 2625898.93 quoted as
2 625 899 is the same number; 2 625 000 is not.
"""
import logging
import re
from bisect import bisect_left

log = logging.getLogger("cfo.verify")

# Rounding only. Anything looser would wave through a figure that is merely
# near a real one, which is the failure we are looking for. The allowance has
# to follow magnitude: half a krone is nothing against 2,6 million, but half a
# percentage point is most of the difference between a good month and a bad
# one — a flat tolerance would let 4,2 % pass as 3,8 %.
def tolerance(value: float) -> float:
    return 0.51 if abs(value) >= 100 else 0.051

# Things that are numerals but not quantities. Stripped before extraction so
# they neither need support nor provide it.
_URL = re.compile(r"https?://\S+")
_MD_LINK = re.compile(r"\]\([^)]*\)")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NO_DATE = re.compile(r"\b\d{1,2}\.\s?\d{1,2}\.(\d{2,4})?\b")
# Identifiers, not quantities. "konto 1500" and "faktura 6689" name things;
# demanding a source for them flags the label rather than the figure.
_IDENTIFIER = re.compile(
    r"\b(?:konto|kontoen|faktura|fakturanr\.?|fakturanummer|bilag|bilagsnr\.?"
    r"|org\.?\s?nr\.?|kundenr\.?|prosjekt|termin|uke)\.?\s*#?\s*\d+",
    re.IGNORECASE)

# Each shape is matched explicitly. A character class that allowed spaces and
# commas anywhere swallowed "1,2,3" and "12 3.4 56" whole and parsed none of
# it — grouping in Norwegian is spaces in threes, which is a pattern, not a
# set, and JSON arrays make that failure routine.
#
# Two ambiguities are resolved in favour of JSON, because most of the corpus
# is JSON returned by Tripletex:
#   "1.504"  -> decimal 1.504, not 1504. Dot grouping needs two groups or more
#              ("1.234.567"); we format thousands with spaces anyway.
# Known limitation: a JSON array of bare numbers, "[1,2,3]", reads as 1.2 and
# 3, because a comma before a digit is a decimal separator in Norwegian and we
# cannot tell the two apart without parsing. Tripletex results put quoted keys
# after their commas, so this is rare; and the cost is a phantom value in the
# corpus, never a false alarm about the answer.
_NUMBER = re.compile(
    r"""-?\d{1,3}(?:\.\d{3}){2,}(?:,\d+)?        # 1.234.567,89
      | -?\d{1,3}(?:[ \u00a0]\d{3})+(?:,\d+)?     # 1 234 567,89
      | -?\d+(?:[.,]\d+)?                        # 1234.56 | 3,8 | 1920
    """,
    re.VERBOSE)

_MILLION = re.compile(
    r"(-?\d{1,3}(?:[ \u00a0.]\d{3})*(?:,\d+)?|-?\d+(?:[.,]\d+)?)"
    r"\s*mill\.?",
    re.IGNORECASE)



def _clean(text: str) -> str:
    text = _URL.sub(" ", text)
    text = _MD_LINK.sub("] ", text)
    text = _ISO_DATE.sub(" ", text)
    text = _NO_DATE.sub(" ", text)
    return _IDENTIFIER.sub(" ", text)


def _to_float(token: str) -> float | None:
    """Read a number written in any of the shapes this app produces."""
    t = token.strip().replace(" ", " ").replace(" ", " ")
    t = t.rstrip(" .,")
    if not t or not any(c.isdigit() for c in t):
        return None
    neg = t.startswith("-")
    t = t.lstrip("-").strip()
    # Norwegian: space groups thousands, comma is the decimal separator.
    if "," in t:
        whole, _, frac = t.rpartition(",")
        whole = whole.replace(" ", "").replace(".", "")
        if not frac.isdigit() or not (whole.isdigit() or whole == ""):
            return None
        t = f"{whole or '0'}.{frac}"
    else:
        t = t.replace(" ", "")
        # 1.234.567 is grouping; 1.504 and 1234.56 are decimal points. One dot
        # is always a decimal here — we group thousands with spaces, and the
        # corpus is mostly JSON, where a dot is never a separator.
        if t.count(".") > 1:
            t = t.replace(".", "")
    try:
        value = float(t)
    except ValueError:
        return None
    return -value if neg else value


def numbers(text: str) -> set[float]:
    """Every quantity mentioned in a piece of text."""
    if not text:
        return set()
    found: set[float] = set()
    cleaned = _clean(text)
    for m in _MILLION.finditer(cleaned):
        v = _to_float(m.group(1))
        if v is not None:
            found.add(v * 1_000_000)
    for m in _NUMBER.finditer(cleaned):
        v = _to_float(m.group(0))
        if v is not None:
            found.add(v)
    return found


class Corpus:
    """Every number the agent was given this turn, and where it came from.

    Keeping the origin alongside the value is what turns a yes/no check into a
    trail: "2 625 899 came from get_balance_sheet on account 1920" is an answer
    the CEO can act on, where "supported" is not.
    """

    def __init__(self) -> None:
        self._origins: dict[float, set[str]] = {}
        self._sorted: list[float] = []
        self._dirty = False

    def add(self, text: str, source: str = "ukjent") -> None:
        for value in numbers(text):
            known = self._origins.setdefault(value, set())
            if not known:
                self._dirty = True
            known.add(source)

    def __len__(self) -> int:
        return len(self._origins)

    def _index(self) -> list[float]:
        if self._dirty:
            self._sorted = sorted(self._origins)
            self._dirty = False
        return self._sorted

    def trace(self, value: float) -> list[str]:
        """Where this figure could have come from. Empty means nowhere."""
        index = self._index()
        if not index:
            return []
        slack = tolerance(value)
        found: set[str] = set()
        i = bisect_left(index, value - slack)
        while i < len(index) and index[i] <= value + slack:
            found |= self._origins[index[i]]
            i += 1
        return sorted(found)

    def supports(self, value: float) -> bool:
        return bool(self.trace(value))


# A year is a numeral, not a quantity, and demanding a source for 2026 would
# bury the findings that matter.
YEAR_RANGE = (1990, 2100)
# Below this, a number is usually a count, a week number or a day of the month.
# Those are reported separately rather than ignored: still visible, not noisy.
MATERIAL = 100


def _fmt(value: float) -> str:
    whole = abs(value - round(value)) < 1e-9
    text = f"{round(value):,}" if whole else f"{value:,.2f}"
    return text.replace(",", " ")


def _is_year(value: float) -> bool:
    return value.is_integer() and YEAR_RANGE[0] <= value <= YEAR_RANGE[1]


def check(answer: str, corpus: Corpus) -> dict:
    """Trace every figure in the answer back to where the agent got it."""
    material: list[float] = []
    minor: list[float] = []
    traced: list[dict] = []
    for value in sorted(numbers(answer), key=abs, reverse=True):
        if _is_year(value):
            continue
        origins = corpus.trace(value)
        if origins:
            if len(traced) < 30:
                traced.append({"value": value, "from": origins})
            continue
        (material if abs(value) >= MATERIAL else minor).append(value)

    result = {"checked": len(traced) + len(material) + len(minor),
              "supported": len(traced),
              "traced": traced,
              "unverified": material[:20],
              "minor": minor[:20],
              "corpus": len(corpus)}
    if material:
        log.warning("Ubekreftede tall i svaret (%d): %s", len(material),
                    ", ".join(f"{v:,.2f}".replace(",", " ") for v in material[:8]))
    return result


def sources(blocks, names: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """(where it came from, what it said) for one assistant turn.

    Tool results are the point: they are what Tripletex actually returned, and
    a figure that appears in one is a figure the agent was given rather than
    one it produced. Each result is labelled with the tool that produced it, so
    the figure can be traced to a named call rather than to "somewhere".

    `names` maps tool-call ids to tool names and is owned by the caller so it
    survives across the rounds of one turn.
    """
    # The caller keeps this across rounds: a turn that pauses puts the tool
    # call in one round and its result in the next, so a map rebuilt per round
    # is empty exactly when the result arrives, and every figure traces back to
    # "mcp" instead of the tool that fetched it.
    names = {} if names is None else names
    for b in blocks or []:
        if getattr(b, "type", "") in ("mcp_tool_use", "tool_use", "server_tool_use"):
            bid = getattr(b, "id", None)
            if bid:
                names[bid] = getattr(b, "name", "") or "verktøy"

    out: list[tuple[str, str]] = []

    collected: list[str] = []

    def walk(item) -> None:
        if isinstance(item, str):
            collected.append(item)
            return
        if isinstance(item, list):
            for x in item:
                walk(x)
            return
        if isinstance(item, dict):
            for key in ("text", "stdout", "stderr", "content"):
                if key in item:
                    walk(item[key])
            return
        kind = getattr(item, "type", "")
        if kind and "result" not in kind and kind not in ("text",):
            # A tool *call* carries the arguments the model chose; those are not
            # evidence of anything, so only results and text are collected.
            if kind != "tool_use":
                return
        for key in ("text", "stdout", "stderr", "content"):
            if hasattr(item, key):
                walk(getattr(item, key))

    for b in blocks or []:
        kind = getattr(b, "type", "")
        if kind in ("mcp_tool_result", "tool_result", "code_execution_tool_result",
                    "bash_code_execution_tool_result", "web_fetch_tool_result"):
            collected.clear()
            walk(b)
            label = names.get(getattr(b, "tool_use_id", ""), "")
            out.append((label or kind.replace("_tool_result", ""),
                        "\n".join(collected)))
        elif kind in ("mcp_tool_use", "server_tool_use"):
            # The inputs carry the periods and account ranges the agent may
            # quote back, and those it did get from somewhere real.
            collected.clear()
            walk(getattr(b, "input", None))
            out.append((f"{getattr(b, 'name', 'verktøy')} (forespørsel)",
                        "\n".join(collected)))
    return out
