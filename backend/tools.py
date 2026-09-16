"""Tool definitions the CFO agent calls, and their dispatch.

These are shaped around CFO questions, not around REST endpoints: one call
returns a whole statement or a whole ageing, already sign-normalised, instead of
making the model assemble it from raw rows. `tripletex_get` is the escape hatch
for anything not covered — and it is a GET, so the tool surface cannot write.
"""
import json
import logging

from tripletex import TripletexClient, TripletexError

log = logging.getLogger("cfo.tools")

_DATE = {"type": "string", "description": "Dato på formen YYYY-MM-DD."}

TOOLS = [
    {
        "name": "tripletex_profit_and_loss",
        "description": (
            "Resultatregnskap for en periode, gruppert etter norsk kontoplan med "
            "driftsresultat, netto finans og resultat før skatt ferdig beregnet. "
            "Inntekter og kostnader returneres begge som positive tall."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {**_DATE, "description": "Fra og med, YYYY-MM-DD."},
                "date_to": {**_DATE, "description": "Til, EKSKLUSIV. For hele 2026, bruk 2027-01-01."},
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "tripletex_balance_sheet",
        "description": "Balanse per en dato: eiendeler, egenkapital og gjeld med utgående saldo per konto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {**_DATE, "description": "Regnskapsårets start, typisk 1. januar."},
                "date_to": {**_DATE, "description": "Til, EKSKLUSIV — balansen leses per dagen før."},
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "tripletex_monthly_trend",
        "description": (
            "Omsetning, lønnskostnad og driftsresultat måned for måned gjennom et år. "
            "Bruk denne til trend, sesong og utvikling — ikke til én enkelt periode."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"year": {"type": "integer", "description": "Regnskapsår, f.eks. 2026."}},
            "required": ["year"],
        },
    },
    {
        "name": "tripletex_budget",
        "description": "Budsjett per konto for et år. Kombiner med resultatregnskapet for budsjettavvik.",
        "input_schema": {
            "type": "object",
            "properties": {"year": {"type": "integer"}},
            "required": ["year"],
        },
    },
    {
        "name": "tripletex_receivables",
        "description": (
            "Kundefordringer: totalsum, aldersfordeling i forfallsbøtter og alle kunder "
            "rangert med andel. Beløpene inkluderer mva."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"as_of": {**_DATE, "description": "Utelat for i dag."}},
            "required": [],
        },
    },
    {
        "name": "tripletex_revenue_by_customer",
        "description": (
            "Omsetning per kunde i en periode, rangert, med andel og akkumulert andel. "
            "Bruk til konsentrasjonsanalyse. Datterselskaper telles hver for seg."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": _DATE,
                "date_to": {**_DATE, "description": "Til, EKSKLUSIV."},
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "tripletex_get",
        "description": (
            "Hent hvilket som helst Tripletex-endepunkt direkte når ingen av de andre "
            "verktøyene dekker spørsmålet — f.eks. /invoice, /customer, /timesheet, "
            "/employee, /project, /supplierInvoice, /ledger/posting, /order. "
            "Kun lesing; det finnes ingen skrivevei. Full API-referanse: "
            "https://tripletex.no/v2-docs/"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Endepunkt, f.eks. '/invoice' eller '/customer'."},
                "params": {
                    "type": "object",
                    "description": "Spørringsparametre, f.eks. {\"invoiceDateFrom\":\"2026-01-01\"}.",
                    "additionalProperties": True,
                },
            },
            "required": ["path"],
        },
    },
]

# Human labels for the activity feed in the browser.
LABELS = {
    "tripletex_profit_and_loss": "Henter resultatregnskap",
    "tripletex_balance_sheet": "Henter balanse",
    "tripletex_monthly_trend": "Henter månedsutvikling",
    "tripletex_budget": "Henter budsjett",
    "tripletex_receivables": "Henter kundefordringer",
    "tripletex_revenue_by_customer": "Henter omsetning per kunde",
    "tripletex_get": "Spør Tripletex",
    "code_execution": "Regner i Python",
    "bash_code_execution": "Regner i Python",
    # Verktøynavnene MCP-serveren bruker. Uten disse viste grensesnittet
    # "fetch report" og "tripletex run script" på engelsk.
    "fetch_report": "Henter rapport",
    "get_report_details": "Slår opp rapportdefinisjon",
    "get_balance_sheet": "Henter saldobalanse",
    "search_ledger_postings": "Søker i hovedboken",
    "search_invoices": "Henter fakturaer",
    "search_supplier_invoices": "Henter leverandørfakturaer",
    "search_customers": "Slår opp kunder",
    "search_employees": "Slår opp ansatte",
    "search_projects": "Slår opp prosjekter",
    "search_hour_entries": "Henter timeføringer",
    "search_result_budgets": "Henter budsjett",
    "search_orders": "Henter ordrer",
    "search_reminders": "Henter purringer",
    "get_voucher_inbox_count": "Sjekker bilagsinnboks",
    "get_supplier_invoices_for_approval": "Sjekker fakturaer til godkjenning",
    "logged_in_user_info": "Bekrefter selskap",
    "list_active_companies": "Slår opp selskap",
    "get_current_datetime": "Sjekker dato",
    "tripletex_run_script": "Kjører spørring mot Tripletex",
}


def label(name: str, args: dict | None = None) -> str:
    base = LABELS.get(name, name.replace("_", " "))
    if name == "tripletex_get" and args and args.get("path"):
        return f"Spør Tripletex {args['path']}"
    return base


async def dispatch(client: TripletexClient, name: str, args: dict) -> str:
    """Run one tool call and return its result as a JSON string."""
    try:
        if name == "tripletex_profit_and_loss":
            result = await client.profit_and_loss(args["date_from"], args["date_to"])
        elif name == "tripletex_balance_sheet":
            result = await client.balance_sheet(args["date_from"], args["date_to"])
        elif name == "tripletex_monthly_trend":
            result = await client.monthly_trend(int(args["year"]))
        elif name == "tripletex_budget":
            result = await client.budget(int(args["year"]))
        elif name == "tripletex_receivables":
            result = await client.receivables(args.get("as_of"))
        elif name == "tripletex_revenue_by_customer":
            result = await client.revenue_by_customer(args["date_from"], args["date_to"])
        elif name == "tripletex_get":
            result = await client.get(args["path"], **(args.get("params") or {}))
        else:
            return json.dumps({"error": f"Ukjent verktøy: {name}"})
        return json.dumps(result, ensure_ascii=False, default=str)
    except TripletexError as exc:
        log.warning("Tool %s failed: %s", name, exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except KeyError as exc:
        return json.dumps({"error": f"Mangler påkrevd parameter: {exc}"}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — the model should see the failure, not a 500
        log.exception("Tool %s crashed", name)
        return json.dumps({"error": f"Uventet feil i {name}: {exc}"}, ensure_ascii=False)
