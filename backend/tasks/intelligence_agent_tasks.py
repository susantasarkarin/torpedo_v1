"""
Periodic wrappers for the deterministic panel/Cint intelligence agents
(agents/panel_intelligence_agent.py, agents/cint_intelligence_agent.py).

Both agents are zero-AI/model, run in "recommend" autonomy mode only
(generates/mirrors real analysis and creates human-review tasks via
app.services.ai_engine -- never autonomously changes a panelist record,
buyer relationship, allocation, or campaign), and were validated against
real production data before this scheduling was added -- see
docs/AI_MIGRATION_STATUS.md.

panel_intelligence_agent's batch is capped (see PANEL_LIMIT below): a real
performance finding during this scheduling work is that
panel_invitation_log has NO index on panelist_id, so the agent's per-batch
$in aggregation is currently an unindexed collection scan over 3.46M
documents regardless of batch size. Capping keeps each run's cost bounded
until that index exists; the cap should be raised (or removed) once it
does. cint_intelligence_agent's aggregation groups the whole cint_surveys
collection directly (no unindexed lookup by a per-item id list), so it
does not need the same caution.
"""

import logging

from celery_app import celery_app

logger = logging.getLogger(__name__)

# See module docstring: bounded until panel_invitation_log.panelist_id is indexed.
PANEL_LIMIT = 5000


@celery_app.task(
    name="backend.tasks.intelligence_agent_tasks.run_panel_intelligence",
    bind=True,
    max_retries=1,
    default_retry_delay=1800,
)
def run_panel_intelligence(self, limit: int = None):
    """Daily: mirror panel activity, flag fraud/fatigue signals. Recommend
    mode only -- creates review tasks, never acts on a panelist record."""
    try:
        from agents.panel_intelligence_agent import run
        result = run(autonomy_mode="recommend", limit=limit or PANEL_LIMIT, dry_run=False)
        logger.info(f"[panel-intelligence] daily run done: {result}")
        return result
    except Exception as e:
        logger.error(f"[panel-intelligence] daily run failed: {e}", exc_info=True)
        raise self.retry(exc=e)


@celery_app.task(
    name="backend.tasks.intelligence_agent_tasks.run_cint_intelligence",
    bind=True,
    max_retries=1,
    default_retry_delay=1800,
)
def run_cint_intelligence(self, limit: int = None):
    """Daily: score real Cint buyer performance, flag underperformers.
    Recommend mode only -- creates review tasks, never touches the Cint API,
    allocation, or pricing."""
    try:
        from agents.cint_intelligence_agent import run
        result = run(autonomy_mode="recommend", limit=limit, dry_run=False)
        logger.info(f"[cint-intelligence] daily run done: {result}")
        return result
    except Exception as e:
        logger.error(f"[cint-intelligence] daily run failed: {e}", exc_info=True)
        raise self.retry(exc=e)
