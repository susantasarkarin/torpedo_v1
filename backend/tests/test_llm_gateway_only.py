"""All LLM calls go through platform_core/ladder.py (Haiku, then Sonnet, then review queue).

The files listed in LEGACY_DIRECT_CALLERS still use a provider SDK or client
directly. They move to platform_core.ladder module by module and are removed
from the list as they go; the list shrinks to zero. A NEW file that calls a
model directly fails this test.
"""
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERN = re.compile(r"chat/completions|bedrock_client|claude_gateway|ai_gateway|anthropic\.Anthropic|import anthropic|boto3\.client\(\"bedrock|import openai|from openai")
GATEWAY = "platform_core/ladder.py"
LEGACY_DIRECT_CALLERS = {  # remove entries as callers move to platform_core.ladder
    "agents/base_agent.py",
    "ai_governance/__init__.py",
    "ai_governance/ai_gateway.py",
    "ai_governance/claude_gateway.py",
    "ai_governance/governance_checks.py",
    "app/services/ai_classification_service.py",
    "app/services/outreach/reply_handler.py",
    "app/tasks/outreach_tasks.py",
    "email_sync/historical_classifier.py",
    "email_sync/llm_email_classifier.py",
    "leads/ai_classifier.py",
    "leads/ai_email_agents.py",
    "leads/backfill_enrich.py",
    "leads/bedrock_client.py",
    "leads/bucket_classifier.py",
    "leads/email_classifier.py",
    "leads/ingestion.py",
    "leads/ingestion_vm.py",
    "leads/outreach_config.py",
    "leads/outreach_mailer.py",
    "leads/query_generator.py",
    "leads/web_search_enrichment.py",
    "outreach_engine/ai_context_generator.py",
    "routers/cold_outreach_router.py",
    "routers/crm.py",
    "routers/prompt_management.py",
    "routers/settings.py",
    "sales/mail_pool_ai.py",
    "sales/mail_pool_llm.py",
    "sales/outreach_pipeline.py",
    "sales/tasks.py",
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
    assert not new, f"call the model through platform_core.ladder, not directly: {new}"
