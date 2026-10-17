"""Norske etiketter for verktøyfeeden i grensesnittet.

Uten disse ser brukeren de rå MCP-navnene — «fetch report», «tripletex run
script» — midt i et ellers norsk grensesnitt.
"""

LABELS = {
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
    "list_pending_attestations": "Sjekker fakturaer til godkjenning",
    "logged_in_user_info": "Bekrefter selskap",
    "list_active_companies": "Slår opp selskap",
    "get_current_datetime": "Sjekker dato",
    "tripletex_run_script": "Kjører spørring mot Tripletex",
    "remember_finding": "Noterer funn",
    "resolve_finding": "Lukker funn",
    "remember_forecast": "Noterer prognose",
    "score_forecast": "Måler prognosen mot fasit",
    "remember_decision": "Noterer beslutning",
    "propose_card": "Legger fram til godkjenning",
    "calculate": "Regner ut",
    "metric": "Regner nøkkeltall",
    "trace_account": "Henter posteringene bak tallet",
    "code_execution": "Regner i Python",
    "bash_code_execution": "Regner i Python",
}


def label(name: str) -> str:
    return LABELS.get(name, name.replace("_", " "))
