"""Marketing > SEO: keywords (approve), opportunities, content gaps, fix plans and packages (MARKETING_PLAN 3.3.4-3.3.6)."""
import os
from datetime import datetime
from typing import Any, Dict

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

from app.security import require
from marketing import schema, seo_plan
from session_state import verify_session

router = APIRouter(prefix="/api/marketing/seo", tags=["Marketing"])
require_approve = require("approve")
SITES_DIR = os.getenv("MARKETING_SITES_DIR", "/var/lib/crm/sites")          # owner's site zips, unzipped per domain
PACKAGES_DIR = os.getenv("MARKETING_PACKAGES_DIR", "/var/lib/crm/seo_packages")


def _gd(n):
    from database import get_database
    return get_database(n)


def _out(rows):
    for r in rows:
        r["_id"] = str(r["_id"])
    return rows


@router.get("/keywords")
async def keywords(user: str = Depends(verify_session)):
    seo_plan.seed_keywords(_gd)
    ea = _gd(schema.DB)
    latest = {}
    for p in ea["keyword_positions"].find({}).sort("date", -1).limit(2000):
        latest.setdefault(p["keyword_id"], p)
    rows = _out(list(ea["keywords"].find({}).sort([("bu", 1), ("status", 1)])))
    for r in rows:
        lp = latest.get(r["_id"]) or {}
        r.update(position=lp.get("position"), impressions_7d=lp.get("impressions"), clicks_7d=lp.get("clicks"))
    return {"keywords": rows}


@router.post("/keywords/{kid}/{action}")
async def keyword_action(kid: str, action: str, user: str = Depends(require_approve)):
    if action not in ("approve", "reject") or not ObjectId.is_valid(kid):
        raise HTTPException(400, "approve | reject")
    _gd(schema.DB)["keywords"].update_one({"_id": ObjectId(kid)}, {"$set": {"status": "approved" if action == "approve" else "rejected",
                                                                           "decided_by": user, "updated_at": datetime.utcnow()}})
    return {"ok": True}


@router.post("/keywords")
async def add_keyword(body: Dict[str, Any] = Body(...), user: str = Depends(require_approve)):
    if body.get("bu") not in schema.BUS or not (body.get("keyword") or "").strip():
        raise HTTPException(400, "bu and keyword required")
    k = body["keyword"].strip().lower()
    _gd(schema.DB)["keywords"].update_one({"bu": body["bu"], "keyword": k}, {"$set": schema.stamp(
        {"keyword": k, "status": "approved", "origin": "owner"}, bu=body["bu"], source="seo_plan", new=False)},
        upsert=True)
    return {"ok": True}


@router.get("/opportunities")
async def opportunities(user: str = Depends(verify_session)):
    return {"opportunities": seo_plan.opportunities(_gd)[:200]}


@router.get("/gaps")
async def gaps(user: str = Depends(verify_session)):
    return {"gaps": _out(list(_gd(schema.DB)["content_gaps"].find({"status": "open"}).sort("created_at", -1).limit(500)))}


@router.get("/fix-plan/{site}")
async def get_fix_plan(site: str, user: str = Depends(verify_session)):
    plan = seo_plan.fix_plan(_gd, site)
    plan.pop("_id", None)
    plan["site_files_uploaded"] = os.path.isdir(os.path.join(SITES_DIR, site))
    return plan


@router.post("/fix-plan/{site}/package")
async def build_package(site: str, user: str = Depends(require_approve)):
    root = os.path.join(SITES_DIR, site)
    if not os.path.isdir(root):
        raise HTTPException(400, f"upload and unzip the site's files to {root} first (MARKETING_AUDIT §4.2)")
    out = seo_plan.apply_package(seo_plan.fix_plan(_gd, site), root, os.path.join(PACKAGES_DIR, site, datetime.utcnow().strftime("%Y%m%d%H%M")))
    return out
