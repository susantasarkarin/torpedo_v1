"""CRM plan 3.1: all Qwen/LLM calls go through platform_core.qwen_gateway.

The files below called a model directly when the gateway was introduced
(2026-10-24). They are moved to the gateway module by module during Phase 3
and removed from this list as they go. A NEW file that calls a model
directly fails this test.
"""
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERN = re.compile(r"chat/completions|local_slm_client|do_inference_client|bedrock_client|openai_wrapper|"
                     r"gemini_enrichment|claude_gateway|openai_gateway|ai_gateway|qwen_client")
GATEWAY = "platform_core/qwen_gateway.py"
LEGACY_DIRECT_CALLERS = {
    "agents/base_agent.py",
    "ai_governance/__init__.py",
    "ai_governance/ai_gateway.py",
    "ai_governance/claude_gateway.py",
    "ai_governance/governance_checks.py",
    "ai_governance/openai_gateway.py",
    "app/services/ai_classification_service.py",
    "app/services/mail_categorizer.py",
    "app/services/outreach/reply_handler.py",
    "app/services/reengagement.py",
    "app/services/rfq_ai.py",
    "app/services/rfq_from_mail.py",
    "app/tasks/outreach_tasks.py",
    "automation/campaign_scheduler.py",
    "automation/email_optimizer.py",
    "automation/reply_engine.py",
    "crm_promote.py",
    "email_sync/historical_classifier.py",
    "email_sync/openai_email_classifier.py",
    "email_sync/router.py",
    "infra/gpu_lease.py",
    "lead_gen_mcp/bounce_handler.py",
    "lead_gen_mcp/query_agent.py",
    "lead_gen_mcp/qwen_client.py",
    "leads/ai_classifier.py",
    "leads/ai_email_agents.py",
    "leads/backfill_enrich.py",
    "leads/batch_enrichment.py",
    "leads/bedrock_client.py",
    "leads/bucket_classifier.py",
    "leads/company_fit.py",
    "leads/do_inference_client.py",
    "leads/email_builder.py",
    "leads/email_classifier.py",
    "leads/email_processor.py",
    "leads/gemini_enrichment.py",
    "leads/imap_leads_service.py",
    "leads/ingestion.py",
    "leads/ingestion_vm.py",
    "leads/local_llm_gate.py",
    "leads/local_slm_client.py",
    "leads/openai_wrapper.py",
    "leads/outreach_config.py",
    "leads/outreach_mailer.py",
    "leads/query_generator.py",
    "leads/query_variants_ai.py",
    "leads/router.py",
    "leads/scheduler.py",
    "leads/web_search_enrichment.py",
    "routers/automation.py",
    "routers/classification.py",
    "routers/cold_outreach_router.py",
    "routers/crm.py",
    "routers/prompt_management.py",
    "routers/settings.py",
    "sales/mail_pool_ai.py",
    "sales/mail_pool_local_ai.py",
    "sales/mail_pool_rfq_extract.py",
    "sales/mailpool_leads.py",
    "sales/outreach_pipeline.py",
    "sales/reply_triage.py",
    "sales/tasks.py",
    "segment_to_finance.py",
    "tasks/cint_survey_scoring.py",
    "tasks/outreach_tasks.py",
}


def test_no_new_direct_llm_callers():
    found = set()
    for root, dirs, files in os.walk(HERE):
        rel_root = os.path.relpath(root, HERE).replace(os.sep, "/")
        if rel_root.split("/")[0] in ("tests", "deprecated", "scripts", "venv", ".venv", "__pycache__"):
            continue
        for f in files:
            if f.endswith(".py"):
                rel = (f if rel_root == "." else f"{rel_root}/{f}")
                with open(os.path.join(root, f), encoding="utf-8", errors="ignore") as fh:
                    if PATTERN.search(fh.read()):
                        found.add(rel)
    new = sorted(found - LEGACY_DIRECT_CALLERS - {GATEWAY})
    assert not new, f"call the model through platform_core.qwen_gateway, not directly: {new}"
