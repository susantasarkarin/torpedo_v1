"""
Router Registry
===============
Central registration of all FastAPI routers that do NOT require service injection
at startup time. Complex routers (traffic, CPX, CINT) remain in main.py because
they need collections / services injected before inclusion.

Usage:
    from router_registry import register_simple_routers
    register_simple_routers(app)
"""

from fastapi import FastAPI


def register_simple_routers(app: FastAPI) -> None:
    """
    Include all routers that need no special initialization context.
    Each registration is wrapped in try/except so one broken router
    never prevents the rest of the application from starting.
    """

    # --- Core infrastructure ---
    try:
        from routers import settings as settings_router
        app.include_router(settings_router.router)
        print("✅ Settings router included")
    except Exception as e:
        print(f"⚠️ Settings router not included: {e}")

    try:
        from routers import health as health_router
        app.include_router(health_router.router)
        print("✅ Health router included")
    except Exception as e:
        print(f"⚠️ Health router not included: {e}")

    try:
        from routers.health_router_v2 import router as health_router_v2
        app.include_router(health_router_v2)
        print("✅ Health router v2 included")
    except Exception as e:
        print(f"⚠️ Health router v2 not included: {e}")

    try:
        from routers import performance as performance_router
        app.include_router(performance_router.router)
        print("✅ Performance router included")
    except Exception as e:
        print(f"⚠️ Performance router not included: {e}")

    # --- Gmail ---
    try:
        from routers import gmail as gmail_router
        app.include_router(gmail_router.router)
        print("✅ Gmail router included (legacy)")
    except Exception as e:
        print(f"⚠️ Gmail router not included: {e}")

    try:
        from routers import gmail_app_router as gmail_api_router
        app.include_router(gmail_api_router.router)
        print("✅ Gmail API router included (new)")
    except Exception as e:
        print(f"⚠️ Gmail API router not included: {e}")

    try:
        from routers import gmail_workspace as gmail_workspace_router
        app.include_router(gmail_workspace_router.router)
        print("✅ Gmail Workspace router included (Service Account)")
    except Exception as e:
        print(f"⚠️ Gmail Workspace router not included: {e}")

    # --- Leads & classification ---
    try:
        from routers import classified_gmail as classified_gmail_router
        app.include_router(classified_gmail_router.router)
        print("✅ Classified Gmail router included")
    except Exception as e:
        print(f"⚠️ Classified Gmail router not included: {e}")

    try:
        from routers import email_patterns as email_patterns_router
        app.include_router(email_patterns_router.router)
        print("✅ Email Patterns router included")
    except Exception as e:
        print(f"⚠️ Email Patterns router not included: {e}")

    try:
        from routers import company_cache as company_cache_router
        app.include_router(company_cache_router.router)
        print("✅ Company Cache router included")
    except Exception as e:
        print(f"⚠️ Company Cache router not included: {e}")

    try:
        from leads.agent_router import router as agent_router
        app.include_router(agent_router)
        print("✅ Lead Generation Agents router included")
    except Exception as e:
        print(f"⚠️ Lead Agents router not included: {e}")

    try:
        from leads.multi_agent_router import router as multi_agent_router
        app.include_router(multi_agent_router)
        print("✅ Multi-Agent System router included")
    except Exception as e:
        print(f"⚠️ Multi-Agent System router not included: {e}")

    try:
        from leads.clay_routes import router as clay_routes
        app.include_router(clay_routes)
        print("✅ Clay-Level Features router included")
    except Exception as e:
        print(f"⚠️ Clay router not included: {e}")

    try:
        from routers import classification as classification_router
        app.include_router(classification_router.router)
        print("✅ Email Classification router included")
    except Exception as e:
        print(f"⚠️ Email Classification router not included: {e}")

    # --- Automation ---
    try:
        from routers import automation as automation_router
        app.include_router(automation_router.router)
        print("✅ Automation System router included")
    except Exception as e:
        print(f"⚠️ Automation System router not included: {e}")

    # --- Panel ---
    try:
        from routers import panel as panel_router
        app.include_router(panel_router.router)
        print("✅ Panel (Survey Panel) router included")
    except Exception as e:
        print(f"⚠️ Panel router not included: {e}")

    try:
        from routers import panel_admin as panel_admin_router
        app.include_router(panel_admin_router.router)
        app.include_router(panel_admin_router.router, prefix="/api")
        print("✅ Panel Admin router included (/panel-admin and /api/panel-admin)")
    except Exception as e:
        print(f"⚠️ Panel Admin router not included: {e}")

    try:
        from routers import panel_invitations as panel_invitations_router
        from routers import panel_ses_webhook as panel_ses_webhook_router
        from routers import panel_join as panel_join_router
        app.include_router(panel_invitations_router.router)
        app.include_router(panel_ses_webhook_router.router)
        app.include_router(panel_join_router.router)
        app.include_router(panel_join_router.router, prefix="/api")
        print("✅ Panel mailing routers included")
    except Exception as e:
        print(f"⚠️ Panel mailing routers not included: {e}")

    # --- Finance / Operations / Sales ---
    try:
        from routers import finance as finance_router
        app.include_router(finance_router.router)
        print("✅ Finance router included")
    except Exception as e:
        print(f"⚠️ Finance router not included: {e}")

    try:
        from routers import operations as operations_router
        app.include_router(operations_router.router)
        print("✅ Operations router included")
    except Exception as e:
        print(f"⚠️ Operations router not included: {e}")

    try:
        from routers import sales_dashboard as sales_dashboard_router
        app.include_router(sales_dashboard_router.router)
        print("✅ Sales Dashboard router included")
    except Exception as e:
        print(f"⚠️ Sales Dashboard router not included: {e}")

    try:
        from routers import sales_accounts as sales_accounts_router
        app.include_router(sales_accounts_router.router)
        print("✅ Sales Accounts router included")
    except Exception as e:
        print(f"⚠️ Sales Accounts router not included: {e}")

    try:
        from routers import unified_vendors as unified_vendors_router
        app.include_router(unified_vendors_router.router)
        print("✅ Unified Vendors router included")
    except Exception as e:
        print(f"⚠️ Unified Vendors router not included: {e}")

    try:
        from routers import vendor_leads as vendor_leads_router
        app.include_router(vendor_leads_router.router)
        print("✅ Vendor Leads router included")
    except Exception as e:
        print(f"⚠️ Vendor Leads router not included: {e}")

    # --- Outreach / Campaigns ---
    try:
        from routers import rfq as rfq_router
        app.include_router(rfq_router.router, prefix="/api")
        print("✅ RFQ router included")
    except Exception as e:
        print(f"⚠️ RFQ router not included: {e}")

    try:
        from routers import mail_operations as mail_operations_router
        app.include_router(mail_operations_router.router, prefix="/api")
        print("✅ Mail Operations router included")
    except Exception as e:
        print(f"⚠️ Mail Operations router not included: {e}")

    try:
        from routers import prompt_management as prompt_management_router
        app.include_router(prompt_management_router.router, prefix="/api")
        print("✅ Prompt Management router included")
    except Exception as e:
        print(f"⚠️ Prompt Management router not included: {e}")

    try:
        from routers import email_campaigns as email_campaigns_router
        app.include_router(email_campaigns_router.router)
        print("✅ Email Campaigns router included")
    except Exception as e:
        print(f"⚠️ Email Campaigns router not included: {e}")

    try:
        from routers import deliverability as deliverability_router
        app.include_router(deliverability_router.router)
        print("✅ Deliverability router included")
    except Exception as e:
        print(f"⚠️ Deliverability router not included: {e}")

    try:
        from routers import unified_inbox as unified_inbox_router
        app.include_router(unified_inbox_router.router)
        print("✅ Unified Inbox router included")
    except Exception as e:
        print(f"⚠️ Unified Inbox router not included: {e}")

    try:
        from routers import campaigns as campaigns_router
        app.include_router(campaigns_router.router)
        print("✅ Campaigns router included")
    except Exception as e:
        print(f"⚠️ Campaigns router not included: {e}")

    try:
        from routers import campaign_automation as campaign_automation_router
        app.include_router(campaign_automation_router.router)
        print("✅ Campaign Automation router included")
    except Exception as e:
        print(f"⚠️ Campaign Automation router not included: {e}")

    try:
        from routers import sales_outreach as sales_outreach_router
        app.include_router(sales_outreach_router.router)
        print("✅ Sales Outreach router included")
    except Exception as e:
        print(f"⚠️ Sales Outreach router not included: {e}")

    try:
        from routers import cold_outreach_router as cold_outreach_router_module
        app.include_router(cold_outreach_router_module.router)
        print("✅ Cold Outreach router included")
    except Exception as e:
        print(f"⚠️ Cold Outreach router not included: {e}")

    try:
        from routers import linkedin as linkedin_router
        app.include_router(linkedin_router.router)
        print("✅ LinkedIn Automation router included")
    except Exception as e:
        print(f"⚠️ LinkedIn Automation router not included: {e}")

    # --- Email sync ---
    try:
        from email_sync.router import router as email_sync_router
        app.include_router(email_sync_router, prefix="/api/v1")
        print("✅ Email Sync router included")
    except Exception as e:
        print(f"⚠️ Email Sync router not included: {e}")

    # --- RBAC ---
    try:
        from routers import users as users_router
        app.include_router(users_router.router)
        print("✅ Users router included")
    except Exception as e:
        print(f"⚠️ Users router not included: {e}")

    try:
        from routers import roles as roles_router
        app.include_router(roles_router.router)
        print("✅ Roles router included")
    except Exception as e:
        print(f"⚠️ Roles router not included: {e}")

    try:
        from routers import approvals as approvals_router
        app.include_router(approvals_router.router)
        print("✅ Approvals router included")
    except Exception as e:
        print(f"⚠️ Approvals router not included: {e}")

    # --- Misc ---
    try:
        from routers import audit as audit_router
        app.include_router(audit_router.router)
        print("✅ Audit Trail router included")
    except Exception as e:
        print(f"⚠️ Audit Trail router not included: {e}")

    try:
        from routers import review_queue as review_queue_router
        app.include_router(review_queue_router.router)
        print("✅ AI Review Queue router included")
    except Exception as e:
        print(f"⚠️ AI Review Queue router not included: {e}")

    try:
        from routers import mcp as mcp_router
        app.include_router(mcp_router.router)
        print("✅ MCP Action Router included")
    except Exception as e:
        print(f"⚠️ MCP Action Router not included: {e}")

    try:
        from routers import projects as projects_router
        app.include_router(projects_router.router)
        print("✅ Projects router included")
    except Exception as e:
        print(f"⚠️ Projects router not included: {e}")

    try:
        from routers import support as support_router
        app.include_router(support_router.router)
        print("✅ Support router included")
    except Exception as e:
        print(f"⚠️ Support router not included: {e}")

    # --- Auth / Admin (extracted Phase 8) ---
    try:
        from routers.auth_handler import router as auth_handler_router
        app.include_router(auth_handler_router)
        print("✅ Auth handler router included")
    except Exception as e:
        print(f"⚠️ Auth handler router not included: {e}")

    try:
        from routers.admin_handler import router as admin_handler_router
        app.include_router(admin_handler_router)
        print("✅ Admin handler router included")
    except Exception as e:
        print(f"⚠️ Admin handler router not included: {e}")

    # --- Legacy routes (extracted Phase 8) ---
    try:
        from routers.legacy_campaign import router as legacy_campaign_router
        app.include_router(legacy_campaign_router)
        print("✅ Legacy campaign router included")
    except Exception as e:
        print(f"⚠️ Legacy campaign router not included: {e}")

    try:
        from routers.legacy_leads import router as legacy_leads_router
        app.include_router(legacy_leads_router)
        print("✅ Legacy leads router included")
    except Exception as e:
        print(f"⚠️ Legacy leads router not included: {e}")

    try:
        from routers.legacy_contacts import router as legacy_contacts_router
        app.include_router(legacy_contacts_router)
        print("✅ Legacy contacts router included")
    except Exception as e:
        print(f"⚠️ Legacy contacts router not included: {e}")

    try:
        from routers.legacy_vendors_projects import router as legacy_vp_router
        app.include_router(legacy_vp_router)
        print("✅ Legacy vendors/projects router included")
    except Exception as e:
        print(f"⚠️ Legacy vendors/projects router not included: {e}")
