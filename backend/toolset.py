"""Which Tripletex tools the agent is allowed to see.

Until now "read-only" was a sentence in the agent definition. The connector was
handed all 146 tools the server offers, `send_invoice`, `approve_month`,
`create_salary_run`, `delete_customer` and `send_amelding` — filing the payroll
report to the authorities — among them. A prompt rule is a request; this is the
answer to it.

The toolset is declared closed (`default_config: {"enabled": False}`) and each
tool below is switched back on by name. Anything not listed is not merely
discouraged: it is never offered to the model, so there is no decision for it
to get wrong, and no jailbreak that reaches it.

The list is **not** "everything that reads". It is what the five lanes need —
liquidity, KPIs and budget, the monthly pack, early warnings, and decision
support. Reads outside that are left off on purpose: individual payslips and
tax cards are nobody's business here, and the accountant-portal tools belong to
a job we have said is not ours.

`audit()` exists because this list rots. Tripletex adds tools; a name that is
absent has been renamed or withdrawn, and a name on the server that is not
here has never been looked at by anyone. Both are worth knowing.
"""
import logging

from mcp_client import mcp

log = logging.getLogger("cfo.toolset")

READ_TOOLS: frozenset[str] = frozenset({
    # The ledger itself. `fetch_report` is the workhorse; the rest answer what
    # a report cannot.
    "fetch_report", "get_report_details", "get_balance_sheet",
    "search_ledger_postings", "search_open_postings", "search_accounts",
    "search_vat_types", "search_voucher_types", "search_result_budgets",

    # Receivables and sales — lane 1's collections, lane 2's revenue.
    "search_invoices", "get_invoice", "get_invoice_pdf_url",
    "search_orders", "get_order",
    "search_reminders", "get_reminder", "get_reminder_pdf_url",
    "search_customers", "get_customer", "search_customer_categories",
    "search_contacts", "get_contact",

    # Payables and the voucher backlog — what the pre-flight reads.
    "search_supplier_invoices", "get_supplier_invoice",
    "get_supplier_invoices_for_approval", "search_suppliers", "list_suppliers",
    "get_supplier", "get_voucher_inbox_count", "get_voucher_document",
    "search_expenses", "get_expense",

    # Payroll as a cost, never as individual pay. Payslips, wage compilations
    # and tax cards are deliberately absent.
    "search_employees", "get_employee", "search_employee_categories",
    "search_wage_type_registrations", "list_timesheet_wage_types",
    "get_amelding_status",

    # Hours and projects: unavailable at some companies, essential for pricing
    # at the ones that track them.
    "search_hour_entries", "search_projects", "get_project",
    "search_activities", "get_activities_for_project",
    "search_project_categories", "get_recent_projects_and_activities",

    # Closing, reconciliation and the audit trail — how we judge whether the
    # books can be quoted at all.
    "get_unmatched_bank_transactions", "get_bank_reconciliation_periods",
    "get_change_log", "get_close_group", "get_month_status",
    "get_month_overview", "get_week_status",

    # Company context. `list_company_holidays` is how the due-date arithmetic
    # will learn that the 10th fell on a Saturday.
    "logged_in_user_info", "list_active_companies", "get_current_datetime",
    "list_company_holidays", "search_countries", "search_departments",
    "search_products", "get_vat_registration_status", "lookup_company_in_brreg",

    # Batch reads in one round-trip. The server states this sandbox reaches
    # read-only tools only; we take that on trust, which is why it is named
    # here rather than quietly included.
    "tripletex_run_script",
})


def toolset(server: str = "tripletex") -> dict:
    """The MCP toolset entry: closed by default, opened tool by tool."""
    return {
        "type": "mcp_toolset",
        "mcp_server_name": server,
        "default_config": {"enabled": False},
        "configs": {name: {"enabled": True} for name in sorted(READ_TOOLS)},
    }


async def audit() -> dict:
    """Compare the allowlist against what the server actually offers."""
    tools = await mcp.list_tools()
    live = {t["name"] for t in tools}
    missing = sorted(READ_TOOLS - live)
    unlisted = sorted(live - READ_TOOLS)
    if missing:
        log.warning("Lesetilgang viser til verktøy som ikke finnes lenger: %s",
                    ", ".join(missing))
    return {"server_tools": len(live), "allowed": len(READ_TOOLS & live),
            "missing": missing, "unlisted": unlisted}
