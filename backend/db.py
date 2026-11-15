"""
Single Mongo entry point for the backend.

Every module should get its database handles from here instead of
constructing MongoClient / AsyncIOMotorClient itself. All handles share the
one process-wide client pair owned by ``database.DatabaseManager`` (sync
pool 30, async pool 50), so calling these helpers per request is free: no
new connection pool is created.

Usage::

    from db import crm, finance, mail, outreach, panel, settings
    crm().accounts.find_one({...})

    from db import crm_async
    await crm_async().accounts.find_one({...})

Database names are fixed here and nowhere else. Do not add a new database
without a reason recorded in docs/mongo_restructure_plan.md.
"""
from __future__ import annotations

try:  # the backend runs with its own directory on sys.path (uvicorn main:app)
    from database import get_database as _get_database, get_async_database as _get_async_database
    from database import get_client, get_async_client  # re-exported for the few callers that need a raw client
except ImportError:  # imported as backend.db from the repo root (tests, scripts)
    from backend.database import get_database as _get_database, get_async_database as _get_async_database  # type: ignore
    from backend.database import get_client, get_async_client  # type: ignore

# --- canonical database names -------------------------------------------------
DB_CRM = "crm_db"                      # system of record: accounts, contacts, opportunities, leads, projects
DB_FINANCE = "finance_db"              # customers, invoices, bills, payments, vendors (finance view)
DB_MAIL = "torpedo_gmail"              # mail pool: email_metadata, workspace_mailboxes, sync state
DB_OUTREACH = "torpedo"                # outreach v2: outreach_leads_v2, outreach_sends_v2, suppression
DB_PANEL = "campaign_platform"         # survey panel: panelists, invitations, rewards
DB_SETTINGS = "torpedo_settings"       # app_settings, config, support tickets
DB_LEGACY = "email_automation"         # legacy catch-all; being drained, see the restructure plan
DB_CINT = "cint_research"
DB_CPX = "cpx_research"
DB_TRAFFIC = "traffic_flow_db"
DB_AI_GOVERNANCE = "ai_governance"

__all__ = [
    "get_client", "get_async_client",
    "crm", "finance", "mail", "outreach", "panel", "settings", "legacy",
    "cint", "cpx", "traffic", "ai_governance", "by_name",
    "crm_async", "finance_async", "mail_async", "outreach_async", "panel_async",
    "settings_async", "legacy_async", "cint_async", "cpx_async", "traffic_async", "by_name_async",
    "DB_CRM", "DB_FINANCE", "DB_MAIL", "DB_OUTREACH", "DB_PANEL", "DB_SETTINGS", "DB_LEGACY",
    "DB_CINT", "DB_CPX", "DB_TRAFFIC", "DB_AI_GOVERNANCE",
]


# --- sync handles (pymongo Database) -------------------------------------------
def crm():            return _get_database(DB_CRM)
def finance():        return _get_database(DB_FINANCE)
def mail():           return _get_database(DB_MAIL)
def outreach():       return _get_database(DB_OUTREACH)
def panel():          return _get_database(DB_PANEL)
def settings():       return _get_database(DB_SETTINGS)
def legacy():         return _get_database(DB_LEGACY)
def cint():           return _get_database(DB_CINT)
def cpx():            return _get_database(DB_CPX)
def traffic():        return _get_database(DB_TRAFFIC)
def ai_governance():  return _get_database(DB_AI_GOVERNANCE)


def by_name(db_name: str):
    """Escape hatch for code that is handed a database name at runtime."""
    return _get_database(db_name)


# --- async handles (motor Database) --------------------------------------------
def crm_async():       return _get_async_database(DB_CRM)
def finance_async():   return _get_async_database(DB_FINANCE)
def mail_async():      return _get_async_database(DB_MAIL)
def outreach_async():  return _get_async_database(DB_OUTREACH)
def panel_async():     return _get_async_database(DB_PANEL)
def settings_async():  return _get_async_database(DB_SETTINGS)
def legacy_async():    return _get_async_database(DB_LEGACY)
def cint_async():      return _get_async_database(DB_CINT)
def cpx_async():       return _get_async_database(DB_CPX)
def traffic_async():   return _get_async_database(DB_TRAFFIC)


def by_name_async(db_name: str):
    return _get_async_database(db_name)
