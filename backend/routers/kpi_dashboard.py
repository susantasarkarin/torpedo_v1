"""Command Centre and module dashboards (CRM plan 3.14). Login required."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.security import require
from kpi import compute, definitions

router = APIRouter(prefix="/api/kpi", tags=["kpi"])
require_read = require("read")
PERIODS = ("today", "week", "mtd", "qtd", "ytd")


def _gd():
    from database import get_database
    return get_database


def _cfg():
    try:
        from platform_core import config_store
        return config_store.get("kpi")
    except Exception:
        return definitions.config_defaults()


def _bu(bu: Optional[str]) -> Optional[str]:
    if bu in (None, "", "ALL", "all"):
        return None
    if bu not in ("SFW", "COGENTIX", "BIM"):
        raise HTTPException(400, "bu must be SFW, COGENTIX, BIM or ALL")
    return bu


@router.get("/definitions")
def kpi_definitions(_user: str = Depends(require_read)):
    return {"definitions": definitions.all_definitions(), "modules": definitions.MODULES, "config": _cfg()}


@router.get("/module/{module}")
def module_dashboard(module: str, period: str = Query("mtd"), bu: Optional[str] = None,
                     _user: str = Depends(require_read)):
    if module not in definitions.MODULES:
        raise HTTPException(404, "unknown module")
    if period not in PERIODS:
        raise HTTPException(400, f"period must be one of {PERIODS}")
    gd, cfg = _gd(), _cfg()
    att = compute.needs_attention(gd, cfg=cfg, limit=200)
    return {"module": module, "period": period, "bu": bu or "ALL",
            "tiles": compute.tiles(gd, module, period, _bu(bu), kpi_cfg=cfg),
            "exceptions": [i for i in att["items"] if i["module"] == module][:50]}


@router.get("/command-centre")
def command_centre(period: str = Query("mtd"), bu: Optional[str] = None, _user: str = Depends(require_read)):
    if period not in PERIODS:
        raise HTTPException(400, f"period must be one of {PERIODS}")
    gd, cfg, now = _gd(), _cfg(), datetime.utcnow()
    s, u, _, _ = compute.period(period, now)
    pulse = compute.tiles(gd, "pulse", period, _bu(bu), now=now, kpi_cfg=cfg)
    comparison = []
    for b in ("SFW", "COGENTIX", "BIM"):
        comparison.append({"bu": b, **{k: compute.value(gd, k, s, u, b) for k in
                                       ("revenue_invoiced", "open_pipeline", "win_rate_90d", "overdue_receivables", "projects_live")}})
    snap = gd("email_automation")["kpi_snapshots"].find_one({"bu": "ALL"}, sort=[("day", -1)]) or {}
    targets = cfg["targets"]
    strip = []
    for m in definitions.MODULES[1:]:
        worst = "none"
        for d in definitions.all_definitions():
            if d["module"] == m:
                st = definitions.rag((snap.get("values") or {}).get(d["key"]), targets.get(d["key"]) or {}, d["higher_is_better"])
                if st == "red" or (st == "amber" and worst != "red") or (st == "green" and worst == "none"):
                    worst = st
        strip.append({"module": m, "status": worst})
    return {"period": period, "bu": bu or "ALL", "pulse": pulse, "needs_attention": compute.needs_attention(gd, now, cfg),
            "module_health": strip, "bu_comparison": comparison, "snapshot_day": snap.get("day")}
