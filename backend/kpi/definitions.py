"""KPI definitions (CRM plan 3.14). Seeded into email_automation.kpi_definitions;
targets and amber/red thresholds come from config section "kpi" (owner).

compute: the function in kpi.compute that produces it, or None when no data
source exists yet -- the tile then says so instead of showing a number.
"""
from typing import Any, Dict, List

# (key, module, name, definition, sources, higher_is_better, unit, compute)
_K = [
    # Command Centre pulse
    ("revenue_invoiced", "pulse", "Revenue invoiced", "Sum of issued invoices dated in the period, INR at latest locked FX",
     ["finance_db.invoices", "finance_db.invoice_fx"], True, "INR", "revenue_invoiced"),
    ("gross_margin_pct", "pulse", "Gross margin %", "(Revenue - vendor - incentive - other direct) / revenue",
     ["finance_db.invoices", "finance_db.bills"], True, "%", None),
    ("cash_collected", "pulse", "Cash collected", "Invoices fully paid in the period (proxy until bank import)",
     ["finance_db.invoices"], True, "INR", "cash_collected"),
    ("overdue_receivables", "pulse", "Overdue receivables", "Balance due on invoices past due date, INR",
     ["finance_db.invoices"], False, "INR", "overdue_receivables"),
    ("dso_days", "pulse", "DSO", "Receivables / revenue last 90 days x 90", ["finance_db.invoices"], False, "days", "dso"),
    ("open_pipeline", "pulse", "Open pipeline", "Quoted, not yet decided (opportunities at proposal, open)",
     ["crm_db.opportunities"], True, "INR", "open_pipeline"),
    ("win_rate_90d", "pulse", "Win rate (90 d, value)", "Won value / (won + closed) value, decided in the last 90 days",
     ["crm_db.opportunities"], True, "%", "win_rate_90d"),
    ("projects_live", "pulse", "Projects live", "Operations projects active (live / soft launch)",
     ["email_automation.projects"], True, "count", "projects_live"),
    ("cash_in_bank", "pulse", "Cash in bank", "Closing balance per bank account, all entities",
     ["bank_transactions"], True, "INR", None),
    # 1 Lead gen & outreach
    ("leads_added", "outreach", "New leads added", "Leads created in the period", ["email_automation.leads_raw"], True, "count", "leads_added"),
    ("mails_sent", "outreach", "Mails sent", "Cold outreach sends in the period", ["torpedo.outreach_sends_v2"], True, "count", "mails_sent"),
    ("reply_rate", "outreach", "Reply rate", "Sends with a reply / sends", ["torpedo.outreach_sends_v2"], True, "%", "reply_rate"),
    ("lead_to_rfq", "outreach", "Lead -> RFQ %", "Leads whose company sent an RFQ", [], True, "%", None),
    # 2 Deliverability
    ("bounce_rate", "deliverability", "Bounce rate", "Bounced / sent in the period", ["torpedo.outreach_sends_v2"], False, "%", "bounce_rate"),
    ("mailboxes_paused", "deliverability", "Mailboxes auto-paused", "Mailboxes paused by the bounce check",
     ["torpedo_gmail.mailboxes"], False, "count", "mailboxes_paused"),
    ("inbox_placement", "deliverability", "Inbox placement %", "Seed test (needs seed inboxes)", [], True, "%", None),
    # 3 Website
    ("visitors", "web", "Visitors", "Distinct visitor cookies in the period", ["email_automation.web_events"], True, "count", "visitors"),
    ("visitors_by_site", "web", "Visitors by site", "Distinct visitors per company site", ["email_automation.web_events"], True, "count", "visitors_by_site"),
    ("form_leads_by_site", "web", "Website enquiries by site", "Form submissions captured as leads, per site",
     ["crm_db.leads"], True, "count", "form_leads_by_site"),
    ("sites_silent", "web", "Sites not sending data", "Installed sites with no tracker data in 24 h", ["email_automation.web_site_checks"], False, "count", "sites_silent"),
    ("identified_pct", "web", "Identified visitors %", "Visitors tied to a contact", ["email_automation.web_visitors"], True, "%", "identified_pct"),
    # 4 Replies
    ("inbound_processed", "replies", "Inbound mails processed", "Mail pipeline decisions in the period",
     ["email_automation.mail_decisions"], True, "count", "inbound_processed"),
    ("auto_handled_pct", "replies", "Auto-handled %", "Decisions not sent to review", ["email_automation.mail_decisions"], True, "%", "auto_handled_pct"),
    # 5 RFQ & pricing
    ("rfqs_received", "rfq", "RFQs received", "RFQs by received date", ["crm_db.opportunities"], True, "count", "rfqs_received"),
    ("median_hours_to_quote", "rfq", "Median time to quote", "Received -> quoted, hours", ["crm_db.opportunities"], False, "hours", "median_hours_to_quote"),
    ("rfqs_awaiting_info", "rfq", "RFQs waiting for client info", "RFQ decisions in awaiting_info", ["email_automation.rfq_decisions"], False, "count", "rfqs_awaiting_info"),
    # 6 Operations
    ("projects_by_status", "ops", "Projects by status", "Lifecycle status counts", ["email_automation.projects"], True, "count", "projects_by_status"),
    ("closed_not_invoiced", "ops", "Closed, not invoiced", "Projects closed with no invoice", ["email_automation.projects"], False, "count", "closed_not_invoiced"),
    # 7 Service Delivery
    ("sd_active", "service_delivery", "Active service projects", "Not closed", ["crm_db.service_projects"], True, "count", "sd_active"),
    # 8 Vendors
    ("bids_requested", "vendors", "Bid requests sent", "Vendor bids requested in the period", ["crm_db.vendor_bids"], True, "count", "bids_requested"),
    # 9 Panel (member store is the SFW panel)
    ("panel_active", "panel", "Active members", "From the SFW panel API", [], True, "count", None),
    # 10 Finance
    ("receivables_aging", "finance", "Receivables aging", "0-30 / 31-60 / 61-90 / 90+ days overdue", ["finance_db.invoices"], False, "INR", "receivables_aging"),
    ("credit_hold_accounts", "finance", "Accounts on credit hold", ">60 days overdue", ["finance_db.invoices"], False, "count", "credit_hold_accounts"),
    # 11 Accounts
    ("accounts_by_engagement", "accounts", "Accounts by engagement", "Active / dormant / lost / dnd (nightly)",
     ["email_automation.reengagement_decisions"], True, "count", "accounts_by_engagement"),
    # 12 System health
    ("review_queue_open", "system", "Review Queue open", "Pending items", ["email_automation.review_queue_items"], False, "count", "review_queue_open"),
    ("qwen_failed", "system", "Qwen failed jobs", "Failed and not retried", ["ai_governance.qwen_jobs"], False, "count", "qwen_failed"),
    ("jobs_failing", "system", "Scheduled jobs failing / missed", "Jobs whose last run errored or was missed",
     ["torpedo_settings.job_runs"], False, "count", "jobs_failing"),
    ("mail_sync_lag_min", "system", "Mail sync lag", "Minutes since the last ingested mail", ["torpedo_gmail.email_metadata"], False, "min", "mail_sync_lag_min"),
]

try:      # 13 Marketing (MARKETING_PLAN 6.1)
    from marketing.kpis import DEFS as _MARKETING
    _K += _MARKETING
except Exception:      # pragma: no cover
    pass

MODULES = ["pulse", "outreach", "deliverability", "web", "replies", "rfq", "ops", "service_delivery", "vendors",
           "panel", "finance", "accounts", "system", "marketing"]


def all_definitions() -> List[Dict[str, Any]]:
    return [{"key": k, "module": m, "name": n, "definition": d, "sources": s, "higher_is_better": h, "unit": u,
             "compute": c} for k, m, n, d, s, h, u, c in _K]


def config_defaults() -> Dict[str, Any]:
    """Targets/thresholds: owner fills; None = no RAG colour, value only."""
    return {"rfq_turnaround_hours": 24,
            "targets": {k: {"target": None, "amber": None, "red": None} for k, *_ in _K}}


def rag(value, t: Dict[str, Any], higher_is_better: bool) -> str:
    if value is None or not isinstance(value, (int, float)) or t.get("red") is None or t.get("amber") is None:
        return "none"
    if higher_is_better:
        return "red" if value < t["red"] else "amber" if value < t["amber"] else "green"
    return "red" if value > t["red"] else "amber" if value > t["amber"] else "green"
