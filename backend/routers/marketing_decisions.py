"""Marketing > Decisions (MARKETING_PLAN 6.1 Decisions section): open recommendations, executed actions with
undo, outcome scorecard per decision type, current autonomy levels. Approve / reject happen in the Review Queue."""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from app.security import require
from marketing import config as mcfg, schema
from session_state import verify_session

router = APIRouter(prefix="/api/marketing/decisions", tags=["Marketing"])
require_approve = require("approve")


def _gd(name):
    from database import get_database
    return get_database(name)


def _row(d):
    keep = ("_id", "decision_type", "entity_label", "entity_key", "bu", "status", "final_action", "final_parameters", "evidence",
            "reasoning", "risks", "validation_problems", "confidence", "autonomy", "gate", "qwen_status", "would_execute",
            "shadow_reason", "outcome", "created_at", "executed_at", "undo_until", "review_item", "impact_inr", "human")
    out = {k: d.get(k) for k in keep}
    out["_id"] = str(d["_id"])
    out["name"] = mcfg.DECISION_TYPES.get(d.get("decision_type"), "")
    return out


@router.get("")
async def list_decisions(status: Optional[str] = None, decision_type: Optional[str] = None, days: int = Query(30, le=365),
                         user: str = Depends(verify_session)) -> Dict[str, Any]:
    q: Dict[str, Any] = {"created_at": {"$gte": datetime.utcnow() - timedelta(days=days)}}
    if status:
        q["status"] = {"$in": status.split(",")}
    if decision_type:
        q["decision_type"] = decision_type
    rows = [_row(d) for d in _gd(schema.DB)["decisions"].find(q).sort("created_at", -1).limit(500)]
    return {"decisions": rows}


@router.get("/scorecard")
async def scorecard(user: str = Depends(verify_session)) -> Dict[str, Any]:
    from marketing import evaluation
    from platform_core import config_store
    cfg = config_store.get("marketing")
    col = _gd(schema.DB)["decisions"]
    ua = evaluation.user_agreement(_gd)
    out = []
    for t, name in mcfg.DECISION_TYPES.items():
        q = {"decision_type": t}
        measured = list(col.find({**q, "outcome": {"$exists": True}}, {"outcome": 1}))
        gate = evaluation.go_live_ok(t, _gd, cfg=cfg)
        set_level = mcfg.autonomy(cfg, t)
        out.append({"type": t, "name": name, "autonomy_set": set_level,
                    "autonomy_effective": set_level if set_level in ("L0", "L1") or gate["ok"] or not cfg.get("enforce_go_live_gate", True) else "L1",
                    "gate": gate["why"], "proposed": col.count_documents(q), "in_review": col.count_documents({**q, "status": "in_review"}),
                    "accepted": col.count_documents({**q, "human": "approved"}), "rejected": col.count_documents({**q, "human": "rejected"}),
                    "executed": col.count_documents({**q, "status": {"$in": ["executed", "shadow_executed"]}}),
                    "agreement_14d": (ua.get(t) or {}).get("agreement"), "measured": len(measured),
                    "better_than_baseline": sum(1 for m in measured if (m.get("outcome") or {}).get("better_than_baseline"))})
    return {"types": out, "mode": cfg.get("mode"), "kill_switch": cfg.get("kill_switch")}


@router.post("/{decision_id}/undo")
async def undo(decision_id: str, user: str = Depends(require_approve)):
    if not ObjectId.is_valid(decision_id):
        raise HTTPException(400, "bad id")
    from marketing import engine
    r = engine.undo(decision_id, user)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error"))
    return r


@router.get("/shadow-report")
async def shadow_report(days: int = Query(14, ge=7, le=90), user: str = Depends(verify_session)):
    """M6: decisions vs owner judgement, predicted vs actual, data freshness, tracking coverage (for M-CP3)."""
    from marketing import shadow_report as SR
    return SR.build(_gd, days=days)


@router.get("/dashboard")
async def dashboard_sections(days: int = Query(30, ge=7, le=365), bu: Optional[str] = None, model: str = "last_non_direct",
                             user: str = Depends(verify_session)):
    """6.1 Sections: website, SEO, paid, social, content, attribution (model switch)."""
    from marketing import attribution, dashboard
    from platform_core import config_store
    if model not in attribution.MODELS:
        raise HTTPException(400, f"model must be one of {attribution.MODELS}")
    if bu not in (None, "", "ALL") and bu not in schema.BUS:
        raise HTTPException(400, "bu must be SFW, COGENTIX, BIM or ALL")
    return dashboard.all_sections(_gd, days=days, bu=None if bu in (None, "", "ALL") else bu, model=model, cfg=config_store.get("marketing"))
