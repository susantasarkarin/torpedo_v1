"""
AI DECISION ENGINE  (Phase 4 foundation)

Adds the safe-autonomy layer on top of the CRM spine:
  - 4 autonomy modes: observe / recommend / approve / autopilot
  - agent registry (default modes + per-agent low-risk actions)
  - executable action queue (ai_action_queue) with an approval gate
  - action handler registry (safe, non-destructive built-ins)

It deliberately reuses existing infrastructure rather than duplicating it:
  - decisions are logged via crm_service.log_ai_decision (ai_decisions collection)
  - entity-level audit is written through the shared audit.AuditLogger (audit_log)
  - it does NOT replace workflows.ApprovalEngine (/api/approvals), which handles
    generic rule-based business approvals (e.g. invoice thresholds). This queue is
    the AI-specific concern: concrete agent actions carrying confidence/risk.

Safety guarantees:
  - Nothing executes automatically unless the agent is in `autopilot` AND the
    action is explicitly low-risk AND a handler exists.
  - `approve` mode always parks the action as `pending` for human approval.
  - No destructive or outbound (email-send) handlers are registered here.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List, Callable, Tuple

from bson import ObjectId
from bson.errors import InvalidId

try:
    from . import crm_service
    from ...audit import AuditLogger
except ImportError:  # pragma: no cover - absolute import fallback
    from app.services import crm_service
    from audit import AuditLogger


QUEUE_COLLECTION = "ai_action_queue"


class AutonomyMode(str, Enum):
    OBSERVE = "observe"        # analyze only
    RECOMMEND = "recommend"    # create suggestions/tasks
    APPROVE = "approve"        # human approval required before action
    AUTOPILOT = "autopilot"    # execute low-risk actions only


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ------------------------------ agent registry ------------------------------

# In-code defaults; override/extend at runtime with register_agent().
DEFAULT_AGENTS: Dict[str, Dict[str, Any]] = {
    "old_mail_classifier": {
        "description": "Classifies old emails and attaches them to CRM records.",
        "default_mode": AutonomyMode.RECOMMEND.value,
        "low_risk_actions": ["log_activity"],
    },
    "reply_monitor": {
        "description": "Monitors cold-outreach replies and drafts responses.",
        "default_mode": AutonomyMode.APPROVE.value,
        "low_risk_actions": ["log_activity"],
    },
    "follow_up_agent": {
        "description": "Detects follow-up gaps and creates tasks/escalations.",
        "default_mode": AutonomyMode.RECOMMEND.value,
        "low_risk_actions": ["create_task", "log_activity"],
    },
    "lead_research_agent": {
        "description": "Researches leads for SFW/Cogentix/BIM and enriches accounts.",
        "default_mode": AutonomyMode.RECOMMEND.value,
        "low_risk_actions": ["create_lead", "create_account", "log_activity"],
    },
}

_AGENTS: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in DEFAULT_AGENTS.items()}


def register_agent(name: str, config: Dict[str, Any]) -> Dict[str, Any]:
    _AGENTS[name] = dict(config)
    return _AGENTS[name]


def get_agents() -> Dict[str, Dict[str, Any]]:
    return {k: dict(v) for k, v in _AGENTS.items()}


def get_agent(name: str) -> Optional[Dict[str, Any]]:
    cfg = _AGENTS.get(name)
    return dict(cfg) if cfg else None


# --------------------------- action handler registry ------------------------

# Globally low-risk actions: safe even in autopilot regardless of agent config.
GLOBAL_LOW_RISK = {"create_task", "log_activity"}

# action_type -> canonical entity type (for audit logging).
_ACTION_ENTITY = {
    "create_task": "task",
    "log_activity": "activity",
    "create_lead": "lead",
    "create_account": "account",
}

_HANDLERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}


def register_action_handler(action_type: str, handler: Callable[[Dict[str, Any]], Dict[str, Any]]):
    _HANDLERS[action_type] = handler


def available_actions() -> List[str]:
    return sorted(_HANDLERS.keys())


# Built-in safe handlers — all route through the canonical spine service.
def _h_create_task(payload):
    return crm_service.create("tasks", payload)


def _h_log_activity(payload):
    return crm_service.log_activity(payload)


def _h_create_lead(payload):
    return crm_service.create("leads", payload)


def _h_create_account(payload):
    name = payload.get("name")
    account, _created = crm_service.get_or_create_account(name, payload.get("defaults"))
    return account


register_action_handler("create_task", _h_create_task)
register_action_handler("log_activity", _h_log_activity)
register_action_handler("create_lead", _h_create_lead)
register_action_handler("create_account", _h_create_account)


# --------------------------------- internals --------------------------------

def _queue_col():
    return crm_service._db()[QUEUE_COLLECTION]


def _audit():
    return AuditLogger(crm_service._db())


def _oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError):
        raise ValueError(f"Invalid id: {id_str}")


def _is_low_risk(agent_name: str, action_type: Optional[str], risk: str) -> bool:
    if action_type is None or action_type not in _HANDLERS:
        return False
    if risk != RiskLevel.LOW.value:
        return False
    agent = get_agent(agent_name) or {}
    allowed = set(agent.get("low_risk_actions", [])) | GLOBAL_LOW_RISK
    return action_type in allowed


def _enqueue(decision_id, agent_name, action_type, payload, mode, risk, status="pending") -> dict:
    doc = {
        "decision_id": decision_id,
        "agent_name": agent_name,
        "action_type": action_type,
        "payload": payload or {},
        "autonomy_mode": mode,
        "risk": risk,
        "status": status,
        "created_at": datetime.utcnow(),
        "decided_by": None,
        "decided_at": None,
        "executed_at": None,
        "result": None,
        "error": None,
    }
    res = _queue_col().insert_one(doc)
    doc["_id"] = str(res.inserted_id)
    return doc


def _execute_action(action_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    handler = _HANDLERS.get(action_type)
    if not handler:
        raise ValueError(f"No handler registered for action_type '{action_type}'")
    return handler(payload or {})


# ------------------------------- public API ---------------------------------

def submit_decision(
    agent_name: str,
    *,
    decision: str,
    recommended_action: Optional[str] = None,
    action_type: Optional[str] = None,
    action_payload: Optional[Dict[str, Any]] = None,
    confidence: Optional[float] = None,
    reason: Optional[str] = None,
    autonomy_mode: Optional[str] = None,
    risk: str = RiskLevel.MEDIUM.value,
    linked_object_type: Optional[str] = None,
    linked_object_id: Optional[str] = None,
    input_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Entry point for every agent action. Logs an ai_decision, then routes by
    autonomy mode. Returns {decision, queued, executed, task} (nulls as applicable).
    """
    mode = autonomy_mode or (get_agent(agent_name) or {}).get("default_mode") or AutonomyMode.OBSERVE.value

    dec = crm_service.log_ai_decision(
        {
            "agent_name": agent_name,
            "linked_object_type": linked_object_type,
            "linked_object_id": linked_object_id,
            "input_summary": input_summary or {},
            "decision": decision,
            "confidence": confidence,
            "reason": reason,
            "recommended_action": recommended_action,
            "autonomy_mode": mode,
            "risk": risk,
            "status": "pending",
        }
    )
    decision_id = dec["_id"]
    out: Dict[str, Any] = {"decision": dec, "queued": None, "executed": None, "task": None}

    if mode == AutonomyMode.OBSERVE.value:
        crm_service.update("ai_decisions", decision_id, {"status": "observed"})

    elif mode == AutonomyMode.RECOMMEND.value:
        task = crm_service.create(
            "tasks",
            {
                "title": recommended_action or decision,
                "status": "pending",
                "linked_object_type": linked_object_type,
                "linked_object_id": linked_object_id,
                "metadata": {"ai_decision_id": decision_id, "agent": agent_name, "source": "ai"},
            },
        )
        crm_service.update(
            "ai_decisions", decision_id, {"status": "recommended", "executed_action": "created_task"}
        )
        out["task"] = task

    elif mode == AutonomyMode.APPROVE.value:
        out["queued"] = _enqueue(decision_id, agent_name, action_type, action_payload, mode, risk)

    elif mode == AutonomyMode.AUTOPILOT.value:
        if _is_low_risk(agent_name, action_type, risk):
            queued = _enqueue(decision_id, agent_name, action_type, action_payload, mode, risk)
            out["executed"] = _resolve(queued["_id"], approve=True, user="autopilot")
        else:
            # Not low-risk -> fall back to human approval.
            out["queued"] = _enqueue(decision_id, agent_name, action_type, action_payload, mode, risk)
    else:
        raise ValueError(f"Unknown autonomy mode: {mode}")

    # Refresh decision snapshot in the response.
    out["decision"] = crm_service.get("ai_decisions", decision_id)
    return out


def _resolve(queue_id: str, approve: bool, user: str, reason: Optional[str] = None) -> dict:
    """Shared approve/reject path."""
    item = _queue_col().find_one({"_id": _oid(queue_id)})
    if not item:
        raise ValueError("Queue item not found")
    if item.get("status") != "pending":
        raise ValueError(f"Queue item is not pending (status={item.get('status')})")

    decision_id = item.get("decision_id")
    now = datetime.utcnow()

    if not approve:
        _queue_col().update_one(
            {"_id": item["_id"]},
            {"$set": {"status": "rejected", "decided_by": user, "decided_at": now, "error": reason}},
        )
        if decision_id:
            crm_service.update("ai_decisions", decision_id, {"status": "rejected"})
        return crm_service.serialize(_queue_col().find_one({"_id": item["_id"]}))

    # Approve -> execute the action.
    try:
        result = _execute_action(item["action_type"], item.get("payload"))
        _queue_col().update_one(
            {"_id": item["_id"]},
            {"$set": {
                "status": "executed",
                "decided_by": user,
                "decided_at": now,
                "executed_at": now,
                "result": result,
            }},
        )
        if decision_id:
            crm_service.update(
                "ai_decisions",
                decision_id,
                {"status": "executed", "executed_action": item["action_type"], "executed_at": now},
            )
        # Entity-level audit through the shared logger (best-effort).
        entity_type = _ACTION_ENTITY.get(item["action_type"], item["action_type"])
        if isinstance(result, dict) and result.get("_id"):
            _audit().log_create(
                entity_type=entity_type,
                entity_id=result["_id"],
                data=result,
                user_id=user,
                metadata={"source": "ai", "agent": item.get("agent_name"), "ai_decision_id": decision_id},
            )
        return crm_service.serialize(_queue_col().find_one({"_id": item["_id"]}))
    except Exception as e:
        _queue_col().update_one(
            {"_id": item["_id"]},
            {"$set": {"status": "failed", "decided_by": user, "decided_at": now, "error": str(e)}},
        )
        if decision_id:
            crm_service.update("ai_decisions", decision_id, {"status": "failed"})
        raise


def approve_action(queue_id: str, user: str) -> dict:
    return _resolve(queue_id, approve=True, user=user)


def reject_action(queue_id: str, user: str, reason: Optional[str] = None) -> dict:
    return _resolve(queue_id, approve=False, user=user, reason=reason)


def list_queue(status: Optional[str] = None, limit: int = 200) -> List[dict]:
    query = {"status": status} if status else {}
    cursor = _queue_col().find(query).sort("created_at", -1).limit(limit)
    return [crm_service.serialize(d) for d in cursor]


def get_queue_item(queue_id: str) -> Optional[dict]:
    return crm_service.serialize(_queue_col().find_one({"_id": _oid(queue_id)}))


def list_decisions(status: Optional[str] = None, agent_name: Optional[str] = None, limit: int = 200) -> List[dict]:
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    if agent_name:
        query["agent_name"] = agent_name
    return crm_service.list_docs("ai_decisions", query, limit=limit)
