"""Arithmetic the model is not allowed to do in its head.

The agent's job is to decide what to compute and what the answer means. The
computing itself belongs here, in code, where it is exact, repeatable and
inspectable. A model that sums four invoices in prose is usually right and
occasionally, silently, not — and a CFO who is occasionally wrong about a
number is worse than no CFO, because nobody knows which time.

Two entry points, for two different kinds of mistake:

- `calculate` evaluates an arithmetic expression. It guards against slips:
  a dropped digit, a mis-added column, a percentage taken of the wrong base.
- `metric` computes a *named* financial figure — DSO, wage ratio, variance,
  accruing tax. It guards against something worse: knowing the arithmetic and
  getting the finance wrong. Receivables include VAT and P&L revenue does not,
  so a DSO that divides one by the other understates by a fifth. That rule now
  lives in `_dso` instead of in a paragraph the model has to remember.

Everything returns the result *and* the arithmetic written out, so the answer
can show its work with figures the CEO can check by hand.
"""
import ast
import logging
import operator

log = logging.getLogger("cfo.calc")

VAT_RATE = 0.25          # alminnelig sats
TAX_RATE = 0.22          # selskapsskatt

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"min": min, "max": max, "abs": abs, "round": round, "sum": sum}

MAX_EXPONENT = 8         # nothing financial needs more, and it stops a hang


class CalcError(ValueError):
    """The expression could not be evaluated safely or at all."""


def _node(node):
    """Evaluate one AST node. Anything not named here is refused outright —
    an allowlist, for the same reason the toolset is one."""
    if isinstance(node, ast.Expression):
        return _node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalcError(f"Bare tall er tillatt, ikke {node.value!r}")
        return node.value
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise CalcError("Ulovlig regneoperator")
        left, right = _node(node.left), _node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalcError(f"Eksponenten er for stor (maks {MAX_EXPONENT})")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise CalcError("Deling på null")
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _UNARY.get(type(node.op))
        if op is None:
            raise CalcError("Ulovlig fortegn")
        return op(_node(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise CalcError("Bare min, max, abs, round og sum er tilgjengelig")
        if node.keywords:
            raise CalcError("Navngitte argumenter er ikke støttet")
        args = [_node(a) for a in node.args]
        if node.func.id == "sum" and len(args) == 1 and isinstance(args[0], list):
            return sum(args[0])
        return _FUNCS[node.func.id](*args)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_node(e) for e in node.elts]
    raise CalcError("Uttrykket inneholder noe som ikke er ren regning")


def evaluate(expression: str) -> float:
    if len(expression) > 500:
        raise CalcError("Uttrykket er for langt")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalcError(f"Klarte ikke lese uttrykket: {exc.msg}") from exc
    value = _node(tree)
    if isinstance(value, list):
        raise CalcError("Uttrykket ga en liste, ikke et tall")
    if value != value or value in (float("inf"), float("-inf")):
        raise CalcError("Regnestykket ga ikke et brukbart tall")
    return float(value)


# ------------------------------------------------------------- formatting
# Formatting is arithmetic too: rounding and separators decide what the CEO
# reads, so they are not left to the model either.

def kr(value: float) -> str:
    return f"{round(value):,}".replace(",", " ") + " kr"


def pct(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}".replace(".", ",") + " %"


def num(value: float, decimals: int = 2) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{round(value):,}".replace(",", " ")
    return f"{value:.{decimals}f}".replace(".", ",")


def days(value: float) -> str:
    return f"{round(value)} dager"


# ---------------------------------------------------------------- metrics

def _need(inputs: dict, *names: str) -> list[float]:
    out = []
    for n in names:
        if inputs.get(n) is None:
            raise CalcError(f"Mangler «{n}»")
        try:
            out.append(float(inputs[n]))
        except (TypeError, ValueError) as exc:
            raise CalcError(f"«{n}» er ikke et tall") from exc
    return out


def _share(i):
    part, whole = _need(i, "part", "whole")
    if whole == 0:
        raise CalcError("Grunnlaget er null")
    v = part / whole * 100
    return {"value": round(v, 1), "unit": "%", "formatted": pct(v),
            "shown": f"{num(part)} / {num(whole)} × 100 = {pct(v)}"}


def _change(i):
    now, before = _need(i, "now", "before")
    if before == 0:
        raise CalcError("Sammenligningsgrunnlaget er null")
    v = (now - before) / abs(before) * 100
    return {"value": round(v, 1), "unit": "%", "formatted": pct(v),
            "shown": f"({num(now)} − {num(before)}) / {num(abs(before))} × 100 = {pct(v)}"}


def _variance(i):
    actual, budget = _need(i, "actual", "budget")
    gap = actual - budget
    out = {"value": round(gap, 2), "unit": "kr", "formatted": kr(gap),
           "shown": f"{num(actual)} − {num(budget)} = {kr(gap)}"}
    if budget:
        p = gap / abs(budget) * 100
        out["pct"] = round(p, 1)
        out["shown"] += f" ({pct(p)} av budsjett)"
    return out


def _margin(i):
    result, revenue = _need(i, "result", "revenue")
    if revenue == 0:
        raise CalcError("Omsetningen er null")
    v = result / revenue * 100
    return {"value": round(v, 1), "unit": "%", "formatted": pct(v),
            "shown": f"{num(result)} / {num(revenue)} × 100 = {pct(v)}",
            "note": f"Av hver hundrelapp fakturert blir {num(round(v, 1))} kroner igjen."}


def _wage_ratio(i):
    wages, revenue = _need(i, "wages", "revenue")
    if revenue == 0:
        raise CalcError("Omsetningen er null")
    v = wages / revenue * 100
    return {"value": round(v, 1), "unit": "%", "formatted": pct(v),
            "shown": f"{num(wages)} / {num(revenue)} × 100 = {pct(v)}",
            "note": (f"Ett prosentpoeng er {kr(revenue / 100)} på bunnlinjen. "
                     f"Av hver hundrelapp går {num(round(v, 1))} kroner til lønn.")}


def _dso(i):
    receivables, revenue, period = _need(i, "receivables", "revenue", "days")
    rate = float(i.get("vat_rate", VAT_RATE))
    gross = revenue * (1 + rate)
    if gross == 0:
        raise CalcError("Omsetningen er null")
    v = receivables / gross * period
    return {"value": round(v, 1), "unit": "dager", "formatted": days(v),
            "shown": (f"{num(receivables)} / ({num(revenue)} × {num(1 + rate)}) "
                      f"× {num(period)} = {days(v)}"),
            "note": ("Omsetningen er brutto opp med mva før divisjonen, fordi "
                     "kundefordringene inkluderer mva og resultatregnskapet "
                     "ikke gjør det. Uten den justeringen blir kredittiden "
                     "omtrent en femdel for kort.")}


def _annualise(i):
    value, elapsed = _need(i, "value", "days_elapsed")
    if elapsed == 0:
        raise CalcError("Ingen dager har gått")
    v = value / elapsed * 365
    return {"value": round(v, 2), "unit": "kr", "formatted": kr(v),
            "shown": f"{num(value)} / {num(elapsed)} × 365 = {kr(v)}",
            "note": "Framskrevet på dagens tempo, ikke en prognose."}


def _per_head(i):
    value, heads = _need(i, "value", "headcount")
    if heads == 0:
        raise CalcError("Ingen ansatte")
    v = value / heads
    return {"value": round(v, 2), "unit": "kr", "formatted": kr(v),
            "shown": f"{num(value)} / {num(heads)} = {kr(v)}",
            "note": ("Antall ansatte er hoder, ikke årsverk. Er mange på deltid, "
                     "er tallet per årsverk høyere.")}


def _runway(i):
    cash, burn = _need(i, "cash", "monthly_cost")
    if burn <= 0:
        raise CalcError("Månedskostnaden må være positiv")
    v = cash / burn
    return {"value": round(v, 1), "unit": "måneder",
            "formatted": f"{num(v, 1)} måneder",
            "shown": f"{num(cash)} / {num(burn)} = {num(v, 1)} måneder"}


def _accruing_tax(i):
    pre_tax, = _need(i, "pre_tax")
    rate = float(i.get("rate", TAX_RATE))
    v = pre_tax * rate
    return {"value": round(v, 2), "unit": "kr", "formatted": kr(v),
            "shown": f"{num(pre_tax)} × {num(rate)} = {kr(v)}",
            "note": ("Mange småselskaper bokfører skatten først ved årsslutt, "
                     "så et sterkt delårsresultat er overvurdert med dette "
                     "beløpet til den er ført.")}


def _vat_gross(i):
    net, = _need(i, "net")
    rate = float(i.get("vat_rate", VAT_RATE))
    v = net * (1 + rate)
    return {"value": round(v, 2), "unit": "kr", "formatted": kr(v),
            "shown": f"{num(net)} × {num(1 + rate)} = {kr(v)}"}


def _vat_net(i):
    gross, = _need(i, "gross")
    rate = float(i.get("vat_rate", VAT_RATE))
    v = gross / (1 + rate)
    return {"value": round(v, 2), "unit": "kr", "formatted": kr(v),
            "shown": f"{num(gross)} / {num(1 + rate)} = {kr(v)}"}


METRICS: dict[str, tuple] = {
    "share": (_share, "part, whole", "part as a percentage of whole"),
    "change": (_change, "now, before", "percentage change between two figures"),
    "variance": (_variance, "actual, budget", "gap to budget in kroner and per cent"),
    "margin": (_margin, "result, revenue", "operating margin"),
    "wage_ratio": (_wage_ratio, "wages, revenue",
                   "wages as a share of revenue, with what a point is worth"),
    "dso": (_dso, "receivables, revenue, days [, vat_rate]",
            "days customers take to pay, VAT gross-up applied"),
    "annualise": (_annualise, "value, days_elapsed", "year-end run rate"),
    "per_head": (_per_head, "value, headcount", "per employee, with the FTE caveat"),
    "runway": (_runway, "cash, monthly_cost", "months the money lasts"),
    "accruing_tax": (_accruing_tax, "pre_tax [, rate]", "unbooked corporation tax"),
    "vat_gross": (_vat_gross, "net [, vat_rate]", "net figure grossed up by VAT"),
    "vat_net": (_vat_net, "gross [, vat_rate]", "VAT stripped out of a gross figure"),
}


def metric(name: str, inputs: dict) -> dict:
    entry = METRICS.get(name)
    if entry is None:
        raise CalcError(f"Ukjent nøkkeltall «{name}». Tilgjengelig: "
                        + ", ".join(sorted(METRICS)))
    return entry[0](inputs or {})


def menu() -> str:
    return "\n".join(f"- {n} ({args}) — {desc}"
                     for n, (_, args, desc) in sorted(METRICS.items()))
