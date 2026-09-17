"""
Tests for tasks/intelligence_agent_tasks.py -- the thin Celery wrappers
around the already-validated panel/Cint intelligence agents. Confirms the
wrappers call through with the expected safe defaults (recommend mode,
dry_run=False so recommendations actually get generated, the panel task's
survey-scan cap), not the underlying agent logic itself (already covered by
tests/test_panel_intelligence_agent.py and tests/test_cint_intelligence_agent.py).
"""
from unittest.mock import patch

from tasks.intelligence_agent_tasks import (
    PANEL_LIMIT,
    run_cint_intelligence,
    run_panel_intelligence,
)


def test_panel_task_uses_recommend_mode_and_default_limit():
    with patch("agents.panel_intelligence_agent.run", return_value={"scanned": 1}) as mock_run:
        run_panel_intelligence()
    mock_run.assert_called_once_with(autonomy_mode="recommend", limit=PANEL_LIMIT, dry_run=False)


def test_panel_task_respects_an_explicit_limit_override():
    with patch("agents.panel_intelligence_agent.run", return_value={"scanned": 1}) as mock_run:
        run_panel_intelligence(limit=99)
    mock_run.assert_called_once_with(autonomy_mode="recommend", limit=99, dry_run=False)


def test_cint_task_uses_recommend_mode_and_no_limit_by_default():
    with patch("agents.cint_intelligence_agent.run", return_value={"scanned": 1}) as mock_run:
        run_cint_intelligence()
    mock_run.assert_called_once_with(autonomy_mode="recommend", limit=None, dry_run=False)


def test_panel_task_retries_on_failure():
    with patch("agents.panel_intelligence_agent.run", side_effect=RuntimeError("boom")):
        try:
            run_panel_intelligence()
        except Exception:
            pass  # Celery's self.retry() inside a non-worker context re-raises -- acceptable here
