"""The "marketing" config section (MARKETING_PLAN 4.3, 4.4, 6.3, Section 5 retention).

Guardrails are config; the owner sets them at M-CP2. Everything starts at L1
(recommend only) and in shadow. L3 is refused in code for budget, bids and
anything client-facing, whatever the stored value says.
"""
from typing import Any, Dict

DECISION_TYPES = {
    "D1": "budget_allocation", "D2": "pause_resume", "D3": "bids_targets", "D4": "negative_keywords",
    "D5": "ad_creative", "D6": "audience", "D7": "seo_priorities", "D8": "content_plan",
    "D9": "posting_schedule", "D10": "lead_scoring_routing", "D11": "next_best_action",
    "D12": "experiments", "D13": "anomaly_response", "D14": "weekly_review",
}
LEVELS = ("L0", "L1", "L2", "L3")
NO_L3 = {"D1", "D3", "D5", "D8", "D10", "D11"}      # budget, bids, client-facing copy / contact
LANES = {"D13": "P1", "D2": "P2", "D4": "P2", "D10": "P2", "D11": "P2"}   # the rest P3 (nightly)

DEFAULTS: Dict[str, Any] = {
    "mode": "shadow",                                  # global: shadow logs only, nothing executes
    "kill_switch": {"global": False, "SFW": False, "COGENTIX": False, "BIM": False},
    "autonomy": {d: "L1" for d in DECISION_TYPES},
    "action_modes": {},                                # per action type: "shadow" | "live" (owner, M-CP3)
    "budget": {
        "monthly_cap_inr": {},                         # {"SFW": {"google": 50000}} -- owner; unset = no automatic change
        "max_daily_change_pct": 20,
        "max_weekly_realloc_pct": 15,
        "allow_total_increase": False,
    },
    "pause": {"min_conversions": 5, "min_spend_inr": 5000, "skip_learning_phase": True},
    "bids": {"max_change_pct": 15, "min_days_between": 7},
    "cooldown_days": {"default": 7},
    "contact_cap_per_day": 1,                          # automated touches per person, all channels
    "stop_loss": {"window": 10},
    "undo_days": 30,
    "outcome_window_days": {"D1": 14, "D2": 7, "D3": 14, "D4": 7, "D5": 14, "D6": 28, "D7": 28, "D8": 28,
                            "D9": 28, "D10": 14, "D11": 14, "D12": 14, "D13": 7, "D14": 28},
    "go_live_min_agreement": 0.85,
    "qwen": {"max_input_tokens": {"default": 1200, "D8": 2500, "D14": 3000}, "model_small": "1.5b", "model_large": "7b"},
    "sla_working_hours": {"lead": 1, "comment": 4, "default": 4},
    "retention": {"web_events_months": 13},
    "banned_claims": [],                               # global list; per-BU lists live in brand_voice
}


def autonomy(cfg: Dict[str, Any], decision: str) -> str:
    """Effective autonomy for a decision type: unknown -> L1, L3 capped at L2 where L3 is not allowed."""
    lvl = (cfg.get("autonomy") or {}).get(decision, "L1")
    if lvl not in LEVELS:
        return "L1"
    if lvl == "L3" and decision in NO_L3:
        return "L2"
    return lvl


def killed(cfg: Dict[str, Any], bu: str) -> bool:
    ks = cfg.get("kill_switch") or {}
    return bool(ks.get("global") or ks.get(bu))
