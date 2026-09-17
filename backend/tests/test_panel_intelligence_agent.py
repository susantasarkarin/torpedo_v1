"""
PANEL INTELLIGENCE AGENT — REAL-SCHEMA FIX (2026-09-17)

Covers the correction to agents/panel_intelligence_agent.py's assess_panelist()
and default source_db, made after a direct query against the real production
campaign_platform.panelists collection (224K+ documents) found:

  1. The agent's default source_db ("panel") is empty in production -- the
     real data lives in campaign_platform. Run with no args, exactly as the
     module's own usage docstring shows, it would have scanned zero panelists.
  2. No document in a 200-doc field-union sample carries any of the original
     _SURVEYS_KEYS synonyms (surveys_completed/completes/...) -- Torpedo v1
     does not track per-panelist survey completions at all today. The old
     heuristic would have flagged every panelist with any reward balance as
     "rewards_without_completions", a false positive on missing data.
  3. The real reward field is "rewards_balance", not any of the original
     _REWARDS_KEYS synonyms.
  4. Real status values are active/bounced/confirmed/dnd -- none of the
     original "flagged"/"suspicious"/"fraud"/"banned" check values have ever
     been observed in production.

No live Mongo needed -- assess_panelist() is a pure function, per its own
docstring ("No I/O").
"""
from agents.panel_intelligence_agent import assess_panelist


# ============================================================
# Backward compatibility -- a document WITH completion data behaves
# exactly as before (matches tests/smoke/test_panel_intelligence_agent.py)
# ============================================================

def test_rewards_without_completions_still_flagged_when_field_present():
    result = assess_panelist({"surveys_completed": 0, "rewards_total": 100})
    assert result["risk"] == "high"
    assert "rewards_without_completions" in result["reasons"]


def test_excessive_reward_per_survey_still_flagged():
    result = assess_panelist({"surveys_completed": 2, "rewards_total": 600})
    assert result["risk"] == "high"
    assert "reward_per_survey_too_high" in result["reasons"]


def test_normal_panelist_with_completion_data_is_low():
    result = assess_panelist(
        {"surveys_completed": 10, "rewards_total": 50, "status": "active"})
    assert result["risk"] == "low"


# ============================================================
# The real-schema fix: no completion field present at all
# ============================================================

def test_reward_balance_alone_is_not_flagged_without_completion_data():
    """This is the false-positive the old heuristic would have produced on
    every one of the 224K real panelists: no surveys_completed-equivalent
    field exists in production, so treating its absence as "0 completions"
    would flag anyone with any reward balance. Absent data must not be
    treated as a confirmed zero."""
    result = assess_panelist({"rewards_balance": 25.0, "status": "active"})
    assert result["risk"] == "low"
    assert "rewards_without_completions" not in result["reasons"]


def test_reward_balance_field_name_is_recognized():
    """rewards_balance is the real production field name -- confirmed via a
    live field-union query -- and must be read the same as the legacy
    synonyms when completion data IS present."""
    result = assess_panelist(
        {"surveys_completed": 0, "rewards_balance": 100, "status": "active"})
    assert result["risk"] == "high"
    assert "rewards_without_completions" in result["reasons"]


# ============================================================
# The new, real-schema-backed signal
# ============================================================

def test_rewards_on_bounced_account_is_flagged():
    result = assess_panelist({"rewards_balance": 10.0, "status": "bounced"})
    assert result["risk"] == "high"
    assert "rewards_on_inactive_status:bounced" in result["reasons"]


def test_rewards_on_dnd_account_is_flagged():
    result = assess_panelist({"rewards_balance": 10.0, "status": "dnd"})
    assert result["risk"] == "high"
    assert "rewards_on_inactive_status:dnd" in result["reasons"]


def test_zero_rewards_on_bounced_account_is_not_flagged():
    """The signal is rewards sitting on a dead account, not the bounce
    itself -- a bounced panelist with no balance is unremarkable."""
    result = assess_panelist({"rewards_balance": 0, "status": "bounced"})
    assert result["risk"] == "low"


def test_rewards_on_active_account_is_not_flagged_by_the_new_rule():
    result = assess_panelist({"rewards_balance": 10.0, "status": "active"})
    assert result["risk"] == "low"


def test_rewards_on_confirmed_account_is_not_flagged():
    """"confirmed" is a real, legitimate status (opted in / verified) --
    only bounced/dnd are treated as inactive."""
    result = assess_panelist({"rewards_balance": 10.0, "status": "confirmed"})
    assert result["risk"] == "low"


# ============================================================
# Legacy status-flag check preserved for any source that uses it
# ============================================================

def test_legacy_status_flag_values_still_recognized():
    assert assess_panelist({"status": "flagged"})["risk"] == "high"
    assert assess_panelist({"status": "banned"})["risk"] == "high"


def test_empty_document_is_low_risk():
    assert assess_panelist({})["risk"] == "low"
