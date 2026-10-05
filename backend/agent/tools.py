"""The tools the model may call that run on this server.

Tripletex tools and the Python sandbox both run on Anthropic's side, so
neither can reach this machine's disk. These run here, and they are the only
writes in the product: the CFO's own notebook and the deck of work it has
prepared for the CEO. Neither touches the ledger.

A job names the ones it may use. The rest are never offered to the model, and
`agent/core.py` refuses a call to one rather than running it.
"""
import logging

import calc
import trace

# `cards` and `memory` are imported in run(), when a tool is used, not here.
# The core imports this module, and memory → definitions → industry imports
# the core back. Loading them here would make industry ask for core.Job while
# the core is still half-loaded. That loop closes once the KPI catalogue
# leaves industry.py, as the target map has it.

log = logging.getLogger("cfo.tools")

LOCAL_TOOLS = [
    {
        "name": "remember_finding",
        "description": (
            "Record something you have flagged, so it survives this "
            "conversation and you can follow it up. Use it whenever you raise "
            "an issue the CEO would expect you to still be tracking next week "
            "— a variance, a concentration, an accruing liability, a "
            "reconciliation break. Do not use it for a figure that is merely "
            "interesting, or for anything already listed as an open finding."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Three or four words, e.g. 'Lønnsandel over budsjett'."},
                "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                "statement": {"type": "string", "description": "One sentence: what is wrong and why it matters."},
                "metric": {"type": "string", "description": "Optional name of the figure being tracked."},
                "value": {"type": "number", "description": "Optional value of that figure now, so drift is measurable."},
            },
            "required": ["topic", "severity", "statement"],
        },
    },
    {
        "name": "resolve_finding",
        "description": (
            "Close a finding from your record once it no longer holds — "
            "fixed, collected, reversed, or accepted by the CEO as a "
            "deliberate choice. Pass status 'accepted' for the last of those. "
            "Closing stale findings matters as much as opening them: a record "
            "full of resolved issues makes the live ones invisible."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "finding_id": {"type": "string", "description": "The id as shown in your record, e.g. F003."},
                "outcome": {"type": "string", "description": "One sentence on how it ended, with the figure that settles it."},
                "status": {"type": "string", "enum": ["resolved", "accepted"]},
            },
            "required": ["finding_id", "outcome"],
        },
    },
    {
        "name": "remember_forecast",
        "description": (
            "Put a number you have forecast on the record so it can be scored "
            "against the outcome later. Call it whenever you state what you "
            "expect a period to land at. Record the expected case; add low and "
            "high when you gave a range. A forecast nobody scores teaches "
            "nobody anything."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "The period forecast, e.g. '2026-09' or '2026'."},
                "metric": {"type": "string", "description": "What is being forecast, e.g. 'Omsetning' or 'Driftsresultat'."},
                "expected": {"type": "number"},
                "basis": {"type": "string", "description": "The assumptions behind it, in one sentence."},
                "low": {"type": "number"},
                "high": {"type": "number"},
            },
            "required": ["period", "metric", "expected", "basis"],
        },
    },
    {
        "name": "score_forecast",
        "description": (
            "Record what a period actually landed at, against a forecast you "
            "made earlier. Do this as soon as the period closes and the actual "
            "is fetchable — before offering a new forecast for the next one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "forecast_id": {"type": "string", "description": "The id as shown in your record, e.g. P002."},
                "actual": {"type": "number"},
                "note": {"type": "string", "description": "Optional: what drove the miss."},
            },
            "required": ["forecast_id", "actual"],
        },
    },
    {
        "name": "remember_decision",
        "description": (
            "Record a decision the CEO has made, so the next conversation "
            "starts from it instead of re-arguing it. Use it when the CEO "
            "tells you what they have chosen to do — hold a hire, accept an "
            "exposure, change a price, defer a payment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "description": "What was decided, in the CEO's terms."},
                "context": {"type": "string", "description": "Optional: the figure or finding it responded to."},
            },
            "required": ["decision"],
        },
    },
    {
        "name": "propose_card",
        "description": (
            "Put a piece of prepared work in front of the CEO as a card he can "
            "approve with one tap. Use it when you have found something worth "
            "acting on AND can say what the action is — an overdue customer "
            "with the chase drafted, a price that is below cost, a month-end "
            "pack ready to send. Write the draft in `draft_text` whenever the "
            "action is a message someone has to send; a card that makes him "
            "compose the email himself has saved him nothing. Do not raise a "
            "card for something already on the deck, and do not use it for a "
            "finding with no action attached — that is `remember_finding`."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The finding in one line, with the figure in it, as he would say it."},
                "body": {"type": "string", "description": "Two or three sentences: what it means for him and why it matters now. No accounting terms."},
                "urgency": {"type": "string", "enum": ["high", "medium", "low"]},
                "kind": {"type": "string", "description": "Short tag, e.g. 'collections', 'pricing', 'cash', 'board'."},
                "draft_subject": {"type": "string", "description": "Subject line, when the action is a message."},
                "draft_text": {"type": "string", "description": "The message itself, ready to send, in the CEO's language."},
                "options": {
                    "type": "array",
                    "description": "Two or three buttons. Effects: 'approve' hands over the draft and closes it, 'snooze' brings it back after `days`, 'delegate' records that he is handling it himself, 'dismiss' closes it for good.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "What the button says, e.g. 'Send påminnelsen'."},
                            "effect": {"type": "string", "enum": ["approve", "snooze", "delegate", "dismiss"]},
                            "days": {"type": "number", "description": "For 'snooze': how many days until it comes back."},
                        },
                        "required": ["label", "effect"],
                    },
                },
            },
            "required": ["title", "body", "urgency"],
        },
    },
    {
        "name": "calculate",
        "description": (
            "Work out an arithmetic expression. Use it for EVERY number you "
            "derive — every sum, difference, percentage, ratio and total, "
            "however easy it looks. You are not permitted to do arithmetic in "
            "your head and state the result: adding four invoices is exactly "
            "where a wrong figure slips through unnoticed. Returns the exact "
            "value and the figure formatted in Norwegian, which you quote as "
            "given rather than reformatting yourself. Supports + - * / // % "
            "** and min, max, abs, round, sum."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Plain arithmetic, e.g. '15600 + 18444 + 31200'. Numbers only — no names or units."},
                "label": {"type": "string", "description": "What this figure is, e.g. 'Sum forfalt Skanska'."},
            },
            "required": ["expression"],
        },
    },
    {
        "name": "metric",
        "description": (
            "Compute a named financial figure with its rules already applied. "
            "Prefer this over `calculate` whenever one fits, because these "
            "carry the domain knowledge: `dso` grosses revenue up by VAT "
            "before dividing, `accruing_tax` uses the Norwegian rate, "
            "`per_head` divides by årsverk, read from the employment "
            "percentages, not by heads, "
            "`wage_ratio` tells you what one percentage point is worth in "
            "kroner. Each returns the result, the arithmetic written out, and "
            "a note to pass on to the CEO where one applies.\n\n"
            "Available:\n" + calc.menu()
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "enum": sorted(calc.METRICS)},
                "inputs": {
                    "type": "object",
                    "description": "The named inputs for that metric, as numbers.",
                    "additionalProperties": {"type": "number"},
                },
            },
            "required": ["name", "inputs"],
        },
    },
    {
        "name": "trace_account",
        "description": (
            "Fetch the individual ledger postings behind a balance, so a "
            "figure can be shown as the entries it is made of. Use it whenever "
            "the CEO asks where a number comes from or whether it is right, "
            "when a figure looks wrong and you want to see what is in it, and "
            "whenever you are about to tell him something expensive on the "
            "strength of one balance. Returns each posting with its date, "
            "description, counterparty and amount, and warns you when the "
            "account has more postings than were fetched — in which case the "
            "sum is not the whole account and you must say so."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "account": {"type": "number", "description": "Account number, e.g. 1920."},
                "date_from": {"type": "string", "description": "YYYY-MM-DD, inclusive."},
                "date_to": {"type": "string", "description": "YYYY-MM-DD, inclusive — the last day you mean."},
            },
            "required": ["account", "date_from", "date_to"],
        },
    },
]


NAMES: tuple[str, ...] = tuple(t["name"] for t in LOCAL_TOOLS)


def definitions(names) -> list[dict]:
    """The definitions of these tools, in catalogue order.

    Catalogue order rather than the order asked for: the tool list is part of
    the cached prompt, and a job that lists the same tools differently should
    not pay for a second cache.
    """
    unknown = set(names) - set(NAMES)
    if unknown:
        raise ValueError(f"Ukjent verktøy: {', '.join(sorted(unknown))}")
    return [t for t in LOCAL_TOOLS if t["name"] in names]


async def run(name: str, args: dict) -> str:
    """Execute one local tool. Errors come back to the model as text so it can
    correct itself — a bad id or a malformed sum should not end the turn."""
    import cards
    import memory

    try:
        if name == "remember_finding":
            rec = memory.add_finding(
                topic=args["topic"], severity=args.get("severity", "medium"),
                statement=args["statement"], metric=args.get("metric"),
                value=args.get("value"))
            return f"Recorded as {rec['id']} on {rec['opened']}."
        if name == "resolve_finding":
            rec = memory.resolve_finding(
                args["finding_id"], args.get("outcome", ""),
                args.get("status", "resolved"))
            return f"{rec['id']} closed as {rec['status']}."
        if name == "remember_forecast":
            rec = memory.add_forecast(
                period=args["period"], metric=args["metric"],
                expected=args["expected"], basis=args["basis"],
                low=args.get("low"), high=args.get("high"))
            return f"Recorded as {rec['id']}; it will be scored against the actual."
        if name == "score_forecast":
            rec = memory.score_forecast(
                args["forecast_id"], args["actual"], args.get("note", ""))
            err = rec.get("error_pct")
            kr = lambda v: f"{v:,.0f}".replace(",", " ")  # noqa: E731
            return (f"{rec['id']} scored: expected {kr(rec['expected'])}, "
                    f"actual {kr(rec['actual'])}"
                    + (f", off by {err:+.1f} %." if err is not None else "."))
        if name == "remember_decision":
            rec = memory.add_decision(args["decision"], args.get("context", ""))
            return f"Decision recorded {rec['date']}."
        if name == "trace_account":
            trail = await trace.account(int(args["account"]), args["date_from"],
                                        args["date_to"])
            log.info("spor: konto %s, %s posteringer, sum %s",
                     trail["account"], trail["count"], trail["total"])
            return trace.as_text(trail)
        if name == "calculate":
            value = calc.evaluate(args["expression"])
            label = args.get("label") or "Resultat"
            log.info("calculate: %s = %s (%s)", args["expression"], value, label)
            return (f"{label}: {args['expression']} = {calc.num(value)} "
                    f"(eksakt {value!r}). Oppgi tallet slik det står her.")
        if name == "metric":
            r = calc.metric(args["name"], args.get("inputs") or {})
            log.info("metric %s -> %s", args["name"], r["formatted"])
            out = f"{args['name']}: {r['shown']}"
            if r.get("pct") is not None:
                out += f" [{r['pct']} %]"
            if r.get("note"):
                out += f"\nSi videre: {r['note']}"
            return out
        if name == "propose_card":
            rec = cards.propose(
                title=args["title"], body=args["body"],
                urgency=args.get("urgency", "medium"),
                kind=args.get("kind", "other"), options=args.get("options"),
                draft_subject=args.get("draft_subject", ""),
                draft_text=args.get("draft_text", ""))
            if rec is None:
                return ("A card for this is already waiting or was dismissed. "
                        "Speak to the existing one instead of raising another.")
            return (f"Card {rec['id']} is on his deck with "
                    f"{len(rec['options'])} buttons"
                    + (" and the draft attached." if rec.get("draft") else "."))
    except calc.CalcError as exc:
        return f"Regnestykket gikk ikke: {exc}"
    except memory.NotFound as exc:
        return f"{exc.args[0]}. Check the id against your record."
    except KeyError as exc:
        return f"Missing required field {exc}. Call it again with that field set."
    except Exception as exc:  # noqa: BLE001 — never end a turn on a note-taking failure
        log.exception("Local tool %s failed", name)
        return f"Could not record that: {exc}"
    return f"Unknown tool {name}."
