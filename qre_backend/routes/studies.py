"""
Study & Wave CRUD â€” manages multiple studies/clients and tracking waves.
Each study has its own quotas, respondents, redirects, and module config.
Waves allow brands and ad stimuli to change between fieldwork periods.
"""
import re
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

import cx_survey
import cx_survey_v33

router = APIRouter(prefix="/api/studies", tags=["studies"])

# CX questionnaire engines by study type (v3.3 = Rev 3 + PII module after S3).
CX_ENGINES = {"cx_survey": cx_survey, "cx_survey_v33": cx_survey_v33}


def _db():
    from main import db
    return db


# ---------- Default module configs (template for new studies) ----------

DEFAULT_MODULES = [
    {
        "key": "pain_fever",
        "num": 1,
        "name": "Pain & Fever Relief",
        "brands": [
            "Dolo 650", "Crocin", "Calpol", "Combiflam",
            "Disprin", "Meftal Spas", "Brufen", "D'Cold Total",
        ],
    },
    {
        "key": "cold_cough",
        "num": 2,
        "name": "Cold, Cough & Flu",
        "brands": [
            "Strepsils", "Vicks", "Benadryl", "Corex",
            "Cheston Cold", "Dabur Honitus", "Cofsils", "Himalaya Koflet",
        ],
    },
    {
        "key": "digestive",
        "num": 3,
        "name": "Digestive & Acidity",
        "brands": [
            "Eno", "Gelusil", "Digene", "Pudin Hara",
            "Hajmola", "Pepfiz", "Dabur Sat Isabgol", "Himalaya Gasex",
        ],
    },
    {
        "key": "vitamins",
        "num": 4,
        "name": "Vitamins & Supplements",
        "brands": [
            "Becosules", "Revital H", "Supradyn", "Limcee Vitamin C",
            "Neurobion Forte", "Centrum", "Oziva", "Wellbeing Nutrition",
        ],
    },
    {
        "key": "skin_antifungal",
        "num": 5,
        "name": "Skin & Antifungal",
        "brands": [
            "Candid", "Ring Guard", "Fourderm", "Betadine",
            "Soframycin", "Dermadew", "Cetaphil", "Terbinafine generics",
        ],
    },
    {
        "key": "ayurvedic",
        "num": 6,
        "name": "Ayurvedic / Herbal OTC",
        "brands": [
            "Patanjali", "Himalaya", "Dabur", "Hamdard",
            "Zandu", "Baidyanath", "Kerala Ayurveda", "Charak Pharma",
        ],
    },
]

DEFAULT_AD_STIMULI: list = []   # no ad-test section in this study

DEFAULT_QUOTAS = {
    "total_sample": 1710,
    "cells": {
        # 8 Tier-2 cities (proportional, sum = 1710)
        "lucknow": 243, "jaipur": 195, "indore": 195, "surat": 219,
        "pune": 243, "coimbatore": 195, "warangal": 201, "bhubaneswar": 219,
        # Age bands (570 × 3 = 1710)
        "band1_25_34": 570, "band2_35_44": 570, "band3_45_55": 570,
        # Gender (50/50)
        "female": 855, "male": 855,
        # NCCS (80/20 split)
        "nccs_a": 1368, "nccs_b": 342,
    },
}


# ---------- Pydantic models ----------

class StudyCreate(BaseModel):
    name: str
    client_name: str
    description: str = ""
    # "qre" = existing health-syndicate questionnaire (default, unchanged behaviour);
    # "cx_survey" = IDFC FIRST Bank CX & Sales Process QRE Rev 2/3 (cx_survey module);
    # "cx_survey_v33" = same QRE, Revision 3 / v3.3 with PII module after S3
    #                   (cx_survey_v33 module).
    type: str = "qre"

class WaveCreate(BaseModel):
    label: str = ""
    modules: Optional[list] = None
    ad_stimuli: Optional[list] = None

class ModuleUpdate(BaseModel):
    num: int
    brands: Optional[list] = None
    focalBrand: Optional[str] = None
    focalStatement: Optional[str] = None
    priceLabel: Optional[str] = None
    name: Optional[str] = None

class AdStimulusUpdate(BaseModel):
    slot: int
    label: str = ""
    url: str = ""
    min_view_seconds: int = 5
# ---------- Study CRUD ----------

@router.get("/")
async def list_studies():
    """List all studies."""
    db = _db()
    studies = []
    async for doc in db.studies.find({}, {"waves": 0}).sort("created_at", -1):
        doc["id"] = doc.pop("_id")
        studies.append(doc)
    return studies


@router.post("/")
async def create_study(payload: StudyCreate):
    """Create a new study with default configuration."""
    db = _db()
    study_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc)

    stype = (payload.type or "qre").strip() or "qre"
    is_cx = stype in CX_ENGINES

    # CX surveys use their own quota frame and carry no brand/ad modules.
    quotas = dict(CX_ENGINES[stype].CX_QUOTAS) if is_cx else dict(DEFAULT_QUOTAS)
    modules = [] if is_cx else [dict(m) for m in DEFAULT_MODULES]

    wave_1 = {
        "wave_id": "w1",
        "label": "Wave 1",
        "modules": modules,
        "ad_stimuli": [dict(a) for a in DEFAULT_AD_STIMULI],
        "created_at": now,
        "status": "active",
    }

    study_doc = {
        "_id": study_id,
        "name": payload.name,
        "client_name": payload.client_name,
        "description": payload.description,
        "type": stype,
        "status": "draft",  # draft | live | paused | closed
        "created_at": now,
        "updated_at": now,
        "active_wave_id": "w1",
        "waves": [wave_1],
        "quotas": quotas,
        "redirects": {"complete_url": "", "terminate_url": "", "overquota_url": ""},
    }

    await db.studies.insert_one(study_doc)

    # Create scoped quota counter doc seeded from this study's own quota cells.
    cells = {k: 0 for k in quotas["cells"]}
    cells["_id"] = f"quota_{study_id}"
    await db.quotas.insert_one(cells)

    return {"id": study_id, "name": payload.name, "type": stype}


@router.get("/{study_id}")
async def get_study(study_id: str):
    """Get full study config including current wave."""
    db = _db()
    doc = await db.studies.find_one({"_id": study_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Study not found")
    doc["id"] = doc.pop("_id")
    return doc


@router.get("/{study_id}/cx-config")
async def get_cx_config(study_id: str):
    """Return the CX questionnaire (question bank S–I + quota frame) for a
    cx_survey study. This is what a CX respondent UI / external programmer
    loads to render the survey."""
    db = _db()
    study = await db.studies.find_one(
        {"_id": study_id},
        {"type": 1, "name": 1, "client_name": 1, "status": 1, "redirects": 1},
    )
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    engine = CX_ENGINES.get(study.get("type"))
    if not engine:
        raise HTTPException(status_code=400, detail="Study is not a CX survey")
    payload = engine.config_payload()
    payload.update({
        "study_id": study_id,
        "study_name": study["name"],
        "client_name": study["client_name"],
        "status": study.get("status"),
        "redirects": study.get("redirects", {}),
    })
    return payload


@router.patch("/{study_id}")
async def update_study(study_id: str, updates: dict):
    """Update study-level fields (name, client_name, description, status)."""
    db = _db()
    allowed = {"name", "client_name", "description", "status"}
    safe = {k: v for k, v in updates.items() if k in allowed}
    if not safe:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    safe["updated_at"] = datetime.now(timezone.utc)
    await db.studies.update_one({"_id": study_id}, {"$set": safe})
    return {"ok": True}


@router.delete("/{study_id}")
async def delete_study(study_id: str):
    """Delete a study and all its data."""
    db = _db()
    await db.studies.delete_one({"_id": study_id})
    await db.quotas.delete_one({"_id": f"quota_{study_id}"})
    await db.respondents.delete_many({"study_id": study_id})
    await db.module_counters.delete_one({"_id": f"rotation_{study_id}"})
    return {"ok": True}


# ---------- Quota Management (scoped) ----------

@router.get("/{study_id}/quotas")
async def get_study_quotas(study_id: str):
    """Get quota status for a study — current counts from completed respondents."""
    db = _db()
    study = await db.studies.find_one({"_id": study_id}, {"quotas": 1})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    from services.quota_service import _aggregate_respondent_counts
    limits = study["quotas"]["cells"]
    counts = await _aggregate_respondent_counts(db, study_id)

    result = []
    for key, limit in limits.items():
        current = counts.get(key, 0)
        result.append({
            "quota_key": key, "current": current,
            "limit": limit, "is_full": current >= limit,
        })
    return result


@router.post("/{study_id}/quotas/update")
async def update_study_quota(study_id: str, payload: dict):
    """Update a quota cell limit."""
    db = _db()
    key = payload.get("quota_key")
    limit = payload.get("limit")
    if not key or limit is None:
        raise HTTPException(status_code=400, detail="quota_key and limit required")
    await db.studies.update_one(
        {"_id": study_id},
        {"$set": {f"quotas.cells.{key}": int(limit), "updated_at": datetime.now(timezone.utc)}},
    )
    return {"ok": True}


@router.post("/{study_id}/quotas/reset")
async def reset_study_quotas(study_id: str):
    """Reset all quota counters for a study."""
    db = _db()
    study = await db.studies.find_one({"_id": study_id}, {"quotas": 1})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    reset = {k: 0 for k in study["quotas"]["cells"]}
    reset["_id"] = f"quota_{study_id}"
    await db.quotas.replace_one({"_id": f"quota_{study_id}"}, reset, upsert=True)
    return {"ok": True}


@router.post("/{study_id}/terminate-overquota")
async def terminate_overquota_respondents(study_id: str):
    """Terminate all in-progress respondents whose claimed cohort is over-achieved.

    An over-achieved cohort is any quota cell where completed count >= cell limit.
    In-progress respondents who hold a claim in such a cell are terminated with
    reason ``overquota_<cell_key>`` and their quota counter claims are released.
    Returns a summary of how many respondents were terminated per cell.
    """
    db = _db()
    study = await db.studies.find_one({"_id": study_id}, {"quotas": 1})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    from services.quota_service import _aggregate_respondent_counts, release_quota
    limits = study["quotas"]["cells"]
    counts = await _aggregate_respondent_counts(db, study_id)

    # Identify full / over-achieved cells
    full_cells = {key for key, limit in limits.items() if counts.get(key, 0) >= limit}
    if not full_cells:
        return {"ok": True, "terminated": 0, "message": "No over-achieved quota cells.", "details": {}}

    # Find all in-progress respondents for this study whose quota_claims
    # intersect with at least one full cell.
    terminated_count = 0
    details: dict[str, int] = {}
    now = datetime.now(timezone.utc)

    async for respondent in db.respondents.find(
        {
            "study_id": study_id,
            "status": "in_progress",
            "quota_claims": {"$in": list(full_cells)},
        },
        {"_id": 1, "quota_claims": 1, "vendor_rid": 1},
    ):
        rid = respondent["_id"]
        claims = respondent.get("quota_claims", [])

        # First full cell found in this respondent's claims → use as reason
        reason_key = next((c for c in claims if c in full_cells), "overquota")
        reason = f"overquota_{reason_key}"

        # Release all quota counter claims atomically
        if claims:
            import asyncio as _asyncio
            await _asyncio.gather(*[release_quota(db, qk, study_id) for qk in claims])

        await db.respondents.update_one(
            {"_id": rid},
            {"$set": {
                "status": "terminated",
                "termination_reason": reason,
                "terminated_at": now,
                "quota_claims": [],
                "ip_locked": False,
            }},
        )
        terminated_count += 1
        details[reason_key] = details.get(reason_key, 0) + 1

    return {
        "ok": True,
        "terminated": terminated_count,
        "full_cells": sorted(full_cells),
        "details": details,
    }


@router.post("/{study_id}/retroactive-overquota")
async def retroactive_overquota_study(study_id: str):
    """Reclassify already-completed respondents that over-achieved quota cells.

    Uses the study's own per-cell limits (from study.quotas.cells), not global
    config defaults.  Completed respondents are sorted oldest-first; those
    beyond each cell's limit are reclassified to status='overquota' and have
    their quota_claims released.

    Returns a summary of how many respondents were reclassified per cell.
    """
    import asyncio as _asyncio
    from datetime import timezone as _tz

    db = _db()
    study = await db.studies.find_one({"_id": study_id}, {"quotas": 1})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    limits: dict = study.get("quotas", {}).get("cells", {})
    if not limits:
        return {"ok": True, "reclassified": 0, "details": {}, "message": "Study has no quota cells defined."}

    now = __import__("datetime").datetime.now(_tz.utc)

    # First pass: collect to_reclassify without updating DB yet
    to_reclassify: dict[str, str] = {}  # respondent_id -> cell_key reason

    for quota_key, limit in limits.items():
        cursor = db.respondents.find(
            {"status": "completed", "study_id": study_id, "quota_claims": quota_key},
            {"_id": 1, "completed_at": 1},
        ).sort("completed_at", 1)

        idx = 0
        async for doc in cursor:
            idx += 1
            if idx > limit:
                rid = doc["_id"]
                if rid not in to_reclassify:
                    to_reclassify[rid] = quota_key

    if not to_reclassify:
        return {"ok": True, "reclassified": 0, "details": {}}

    # Second pass: apply updates
    details: dict[str, int] = {}
    update_tasks = []
    for rid, cell_key in to_reclassify.items():
        update_tasks.append(
            db.respondents.update_one(
                {"_id": rid},
                {"$set": {
                    "status": "overquota",
                    "termination_reason": f"overquota_{cell_key}",
                    "terminated_at": now,
                    "quota_claims": [],
                    "ip_locked": False,
                }},
            )
        )
        details[cell_key] = details.get(cell_key, 0) + 1

    await _asyncio.gather(*update_tasks)

    return {
        "ok": True,
        "reclassified": len(to_reclassify),
        "details": details,
    }


# ---------- Redirect Management (scoped) ----------

@router.get("/{study_id}/redirects")
async def get_study_redirects(study_id: str):
    db = _db()
    study = await db.studies.find_one({"_id": study_id}, {"redirects": 1})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    return study.get("redirects", {})


@router.post("/{study_id}/redirects")
async def set_study_redirects(study_id: str, payload: dict):
    db = _db()
    safe = {k: v for k, v in payload.items() if k in {"complete_url", "terminate_url", "overquota_url"}}
    await db.studies.update_one(
        {"_id": study_id},
        {"$set": {f"redirects.{k}": v for k, v in safe.items()},
         "$currentDate": {"updated_at": True}},
    )
    return {"ok": True}


# ---------- Wave Management ----------

@router.get("/{study_id}/waves")
async def list_waves(study_id: str):
    """List all waves for a study."""
    db = _db()
    study = await db.studies.find_one({"_id": study_id}, {"waves": 1, "active_wave_id": 1})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    waves = []
    for w in study.get("waves", []):
        waves.append({
            "wave_id": w["wave_id"],
            "label": w.get("label", ""),
            "status": w.get("status", "draft"),
            "is_active": w["wave_id"] == study.get("active_wave_id"),
            "created_at": str(w.get("created_at", "")),
            "module_count": len(w.get("modules", [])),
        })
    return waves


@router.post("/{study_id}/waves")
async def create_wave(study_id: str, payload: WaveCreate):
    """Create a new wave â€” copies modules from previous wave or uses defaults."""
    db = _db()
    study = await db.studies.find_one({"_id": study_id})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    existing_waves = study.get("waves", [])
    wave_num = len(existing_waves) + 1
    wave_id = f"w{wave_num}"

    # Copy modules from the active wave (allows editing from last known config)
    active_wid = study.get("active_wave_id")
    source_modules = None
    for w in existing_waves:
        if w["wave_id"] == active_wid:
            source_modules = w.get("modules")
            break
    if source_modules is None:
        source_modules = [dict(m) for m in DEFAULT_MODULES]

    if payload.modules:
        modules = payload.modules
    else:
        modules = [dict(m) for m in source_modules]

    ad_stimuli = payload.ad_stimuli if payload.ad_stimuli else [dict(a) for a in DEFAULT_AD_STIMULI]

    new_wave = {
        "wave_id": wave_id,
        "label": payload.label or f"Wave {wave_num}",
        "modules": modules,
        "ad_stimuli": ad_stimuli,
        "created_at": datetime.now(timezone.utc),
        "status": "draft",
    }

    await db.studies.update_one(
        {"_id": study_id},
        {"$push": {"waves": new_wave}, "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    return {"wave_id": wave_id, "label": new_wave["label"]}


@router.post("/{study_id}/waves/{wave_id}/activate")
async def activate_wave(study_id: str, wave_id: str):
    """Set a wave as the active wave for the study."""
    db = _db()
    study = await db.studies.find_one({"_id": study_id})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    # Mark previous active as archived, new as active
    for i, w in enumerate(study.get("waves", [])):
        if w["wave_id"] == wave_id:
            await db.studies.update_one(
                {"_id": study_id},
                {"$set": {
                    "active_wave_id": wave_id,
                    f"waves.{i}.status": "active",
                    "updated_at": datetime.now(timezone.utc),
                }},
            )
            return {"ok": True, "active_wave_id": wave_id}
    raise HTTPException(status_code=404, detail="Wave not found")


# ---------- Module Config (within a wave) ----------

@router.get("/{study_id}/waves/{wave_id}/modules")
async def get_wave_modules(study_id: str, wave_id: str):
    """Get all module configs for a specific wave."""
    db = _db()
    study = await db.studies.find_one({"_id": study_id})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    for w in study.get("waves", []):
        if w["wave_id"] == wave_id:
            return w.get("modules", [])
    raise HTTPException(status_code=404, detail="Wave not found")


@router.patch("/{study_id}/waves/{wave_id}/modules/{module_num}")
async def update_module(study_id: str, wave_id: str, module_num: int, payload: ModuleUpdate):
    """Update brands, focal brand, etc. for a specific module in a wave."""
    db = _db()
    study = await db.studies.find_one({"_id": study_id})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    for wi, w in enumerate(study.get("waves", [])):
        if w["wave_id"] == wave_id:
            for mi, m in enumerate(w.get("modules", [])):
                if m["num"] == module_num:
                    updates = {}
                    if payload.brands is not None:
                        updates[f"waves.{wi}.modules.{mi}.brands"] = payload.brands
                    if payload.focalBrand is not None:
                        updates[f"waves.{wi}.modules.{mi}.focalBrand"] = payload.focalBrand
                    if payload.focalStatement is not None:
                        updates[f"waves.{wi}.modules.{mi}.focalStatement"] = payload.focalStatement
                    if payload.priceLabel is not None:
                        updates[f"waves.{wi}.modules.{mi}.priceLabel"] = payload.priceLabel
                    if payload.name is not None:
                        updates[f"waves.{wi}.modules.{mi}.name"] = payload.name
                    if updates:
                        updates["updated_at"] = datetime.now(timezone.utc)
                        await db.studies.update_one({"_id": study_id}, {"$set": updates})
                    return {"ok": True}
    raise HTTPException(status_code=404, detail="Module or wave not found")


# ---------- Ad Stimuli (within a wave) ----------

@router.get("/{study_id}/waves/{wave_id}/ads")
async def get_wave_ads(study_id: str, wave_id: str):
    db = _db()
    study = await db.studies.find_one({"_id": study_id})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    for w in study.get("waves", []):
        if w["wave_id"] == wave_id:
            return w.get("ad_stimuli", [])
    raise HTTPException(status_code=404, detail="Wave not found")


@router.put("/{study_id}/waves/{wave_id}/ads")
async def set_wave_ads(study_id: str, wave_id: str, ads: list[AdStimulusUpdate]):
    db = _db()
    study = await db.studies.find_one({"_id": study_id})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    for wi, w in enumerate(study.get("waves", [])):
        if w["wave_id"] == wave_id:
            await db.studies.update_one(
                {"_id": study_id},
                {"$set": {
                    f"waves.{wi}.ad_stimuli": [a.model_dump() for a in ads],
                    "updated_at": datetime.now(timezone.utc),
                }},
            )
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Wave not found")


# ---------- Survey Config Endpoint (consumed by frontend) ----------

@router.get("/{study_id}/config")
async def get_survey_config(study_id: str):
    """
    Returns the active wave's module/ad config for the survey frontend.
    This is what the survey UI loads to render brand lists dynamically.
    """
    db = _db()
    study = await db.studies.find_one({"_id": study_id})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    if study.get("status") not in ("live", "draft"):
        raise HTTPException(status_code=400, detail="Study is not active")

    active_wid = study.get("active_wave_id")
    active_wave = None
    for w in study.get("waves", []):
        if w["wave_id"] == active_wid:
            active_wave = w
            break

    if not active_wave:
        raise HTTPException(status_code=400, detail="No active wave configured")

    return {
        "study_id": study_id,
        "study_name": study["name"],
        "client_name": study["client_name"],
        "wave_id": active_wid,
        "wave_label": active_wave.get("label", ""),
        "modules": active_wave.get("modules", []),
        "ad_stimuli": active_wave.get("ad_stimuli", []),
        "quotas": study.get("quotas", {}),
        "redirects": study.get("redirects", {}),
    }


# ---------- Study-scoped Stats & Export ----------

@router.get("/{study_id}/stats")
async def study_stats(study_id: str):
    db = _db()
    study = await db.studies.find_one({"_id": study_id}, {"quotas": 1, "name": 1})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    total = await db.respondents.count_documents({"study_id": study_id})
    completed = await db.respondents.count_documents({"study_id": study_id, "status": "completed"})
    terminated = await db.respondents.count_documents({"study_id": study_id, "status": "terminated"})
    in_progress = await db.respondents.count_documents({"study_id": study_id, "status": "in_progress"})

    pipeline = [
        {"$match": {"study_id": study_id, "status": "terminated"}},
        {"$group": {"_id": "$termination_reason", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    term_reasons = []
    async for doc in db.respondents.aggregate(pipeline):
        term_reasons.append({"reason": doc["_id"], "count": doc["count"]})

    # Median LOI: compute from started_at / completed_at timestamps
    import statistics as _stats
    loi_values = []
    async for doc in db.respondents.find(
        {"study_id": study_id, "status": "completed",
         "started_at": {"$exists": True}, "completed_at": {"$exists": True}},
        {"started_at": 1, "completed_at": 1},
    ):
        try:
            secs = (doc["completed_at"] - doc["started_at"]).total_seconds()
            if secs > 0:
                loi_values.append(secs / 60.0)
        except Exception:
            pass
    median_loi = round(_stats.median(loi_values), 1) if loi_values else None

    # Daily completions (last 30 days)
    daily_pipeline = [
        {"$match": {"study_id": study_id, "status": "completed", "completed_at": {"$exists": True}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$completed_at"}}, "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
        {"$limit": 30},
    ]
    daily_completions = []
    async for doc in db.respondents.aggregate(daily_pipeline):
        daily_completions.append({"date": doc["_id"], "count": doc["count"]})

    target = study["quotas"].get("total_sample", 500)
    return {
        "study_name": study["name"],
        "target_sample": target,
        "total_started": total,
        "completed": completed,
        "terminated": terminated,
        "in_progress": in_progress,
        "completion_rate": round(completed / total * 100, 1) if total > 0 else 0,
        "incidence_rate": round(completed / (completed + terminated) * 100, 1) if (completed + terminated) > 0 else 0,
        "fieldwork_progress": round(completed / target * 100, 1) if target > 0 else 0,
        "termination_reasons": term_reasons,
        "median_loi": median_loi,
        "daily_completions": daily_completions,
    }


def _qid_sort_key(x):
    """Natural sort: leading letters, then trailing number (S10, I3, Q41, A6...)."""
    m = re.match(r'^([A-Za-z_]+)(\d+)$', x)
    if m:
        return (m.group(1), int(m.group(2)))
    return (x, 0)


def _build_study_export_rows(docs, meta_builder):
    """
    Convert respondent docs into export rows with MCQ expansion.
    Multi-select questions (list values) are split into binary indicator
    columns: Q6__c1, Q6__c2, ... = 1 if code selected, 0 otherwise.
    Grid/dict questions are kept as JSON strings. Scalars pass through.
    Returns (rows, meta_fields, q_col_order).
    """
    raw_rows = []
    mcq_codes: dict = {}
    scalar_qids = set()
    dict_qids = set()

    for doc in docs:
        resp = doc.get("responses", {})
        row_base = meta_builder(doc)
        for qid, val in resp.items():
            if isinstance(val, list):
                mcq_codes.setdefault(qid, set()).update(str(v) for v in val)
                row_base[qid] = val
            elif isinstance(val, dict):
                dict_qids.add(qid)
                row_base[qid] = str(val)
            else:
                scalar_qids.add(qid)
                row_base[qid] = str(val) if val is not None else ""
        raw_rows.append(row_base)

    all_qids = sorted(scalar_qids | set(mcq_codes) | dict_qids, key=_qid_sort_key)

    q_columns = []
    for qid in all_qids:
        if qid in mcq_codes:
            for code in sorted(mcq_codes[qid], key=lambda c: (len(c), c)):
                q_columns.append((qid, code))
        else:
            q_columns.append((qid, None))

    rows = []
    for raw in raw_rows:
        row = {k: v for k, v in raw.items() if not isinstance(v, list)}
        for qid, code in q_columns:
            if code is not None:
                raw_val = raw.get(qid, [])
                row[f"{qid}__c{code}"] = 1 if isinstance(raw_val, list) and code in [str(v) for v in raw_val] else 0
            else:
                row[qid] = raw.get(qid, "")
        rows.append(row)

    q_col_order = [f"{qid}__c{code}" if code is not None else qid for qid, code in q_columns]
    return rows, q_col_order


@router.get("/{study_id}/export")
async def export_study_csv(study_id: str, status_filter: str = "completed"):
    """Export study responses as CSV. status_filter: completed | all. MCQs are expanded into separate binary columns."""
    import io, csv
    from fastapi.responses import StreamingResponse

    db = _db()
    query = {"study_id": study_id}
    if status_filter == "completed":
        query["status"] = "completed"

    meta = ["respondent_id", "study_id", "wave_id", "status", "termination_reason",
            "nccs_grade", "nccs_band", "assigned_modules", "started_at", "completed_at"]

    def _meta(doc):
        return {
            "respondent_id": doc["_id"],
            "study_id": doc.get("study_id", ""),
            "wave_id": doc.get("wave_id", ""),
            "status": doc.get("status"),
            "termination_reason": doc.get("termination_reason", ""),
            "nccs_grade": doc.get("nccs_grade", ""),
            "nccs_band": doc.get("nccs_band", ""),
            "assigned_modules": ";".join(str(m) for m in doc.get("assigned_modules", [])),
            "started_at": str(doc.get("started_at", "")),
            "completed_at": str(doc.get("completed_at", "")),
        }

    docs = [doc async for doc in db.respondents.find(query)]
    if not docs:
        return {"message": "No responses to export"}

    rows, q_col_order = _build_study_export_rows(docs, _meta)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=meta + q_col_order, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    output.seek(0)
    study = await db.studies.find_one({"_id": study_id}, {"name": 1})
    raw_name = (study["name"] if study else study_id).replace(" ", "_").lower()
    # HTTP headers must be latin-1; study names can contain em-dashes and other
    # non-ASCII characters, so reduce the filename to a safe ASCII slug.
    fname = re.sub(r"[^A-Za-z0-9_-]", "", raw_name) or study_id
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}_{status_filter}.csv"},
    )


@router.get("/{study_id}/export/spss")
async def export_study_spss(study_id: str, status_filter: str = "completed"):
    """Export study responses as an SPSS .sav file, scoped to this study. MCQs are expanded into separate binary columns."""
    import tempfile, os as _os
    import pandas as pd
    import pyreadstat
    from fastapi.responses import FileResponse

    db = _db()
    query = {"study_id": study_id}
    if status_filter == "completed":
        query["status"] = "completed"

    meta = ["respondent_id", "study_id", "wave_id", "status", "termination_reason",
            "nccs_grade", "nccs_band", "assigned_modules", "started_at", "completed_at"]

    def _meta(doc):
        return {
            "respondent_id": doc["_id"],
            "study_id": doc.get("study_id", ""),
            "wave_id": doc.get("wave_id", ""),
            "status": doc.get("status"),
            "termination_reason": doc.get("termination_reason", ""),
            "nccs_grade": doc.get("nccs_grade", ""),
            "nccs_band": doc.get("nccs_band", ""),
            "assigned_modules": ";".join(str(m) for m in doc.get("assigned_modules", [])),
            "started_at": str(doc.get("started_at", "")),
            "completed_at": str(doc.get("completed_at", "")),
        }

    docs = [doc async for doc in db.respondents.find(query)]
    if not docs:
        return {"message": "No responses to export"}

    rows, q_col_order = _build_study_export_rows(docs, _meta)
    all_cols = meta + q_col_order
    df = pd.DataFrame(rows, columns=all_cols).fillna("")

    study = await db.studies.find_one({"_id": study_id}, {"name": 1})
    raw_name = (study["name"] if study else study_id).replace(" ", "_").lower()
    fname_slug = re.sub(r"[^A-Za-z0-9_-]", "", raw_name) or study_id

    tmp = tempfile.NamedTemporaryFile(suffix=".sav", delete=False)
    tmp.close()
    try:
        pyreadstat.write_sav(df, tmp.name, column_labels=all_cols)
        fname = f"{fname_slug}_{status_filter}.sav"
        return FileResponse(
            tmp.name,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
            background=None,
        )
    except Exception:
        _os.unlink(tmp.name)
        raise


# ---------- Client Dashboard (scoped) ----------

@router.get("/{study_id}/dashboard")
async def study_dashboard(study_id: str):
    """Read-only dashboard data for client sharing, scoped to a study."""
    db = _db()
    study = await db.studies.find_one({"_id": study_id})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    total = await db.respondents.count_documents({"study_id": study_id})
    completed = await db.respondents.count_documents({"study_id": study_id, "status": "completed"})
    terminated = await db.respondents.count_documents({"study_id": study_id, "status": "terminated"})
    in_progress = await db.respondents.count_documents({"study_id": study_id, "status": "in_progress"})

    # Quota fill — derive from completed respondents (source of truth), matching
    # the Manage Quota Cells page; the live counter doc can drift from abandoned
    # in-progress claims.
    from services.quota_service import _aggregate_respondent_counts
    counts = await _aggregate_respondent_counts(db, study_id)
    limits = study["quotas"]["cells"]
    quota_summary = []
    for key, limit in limits.items():
        current = counts.get(key, 0)
        quota_summary.append({
            "cell": key, "filled": current, "target": limit,
            "pct": round(current / limit * 100, 1) if limit > 0 else 0,
        })

    # Daily completions
    daily_pipeline = [
        {"$match": {"study_id": study_id, "status": "completed", "completed_at": {"$exists": True}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$completed_at"}}, "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}, {"$limit": 30},
    ]
    daily = []
    async for doc in db.respondents.aggregate(daily_pipeline):
        daily.append({"date": doc["_id"], "count": doc["count"]})

    # Termination breakdown
    term_pipeline = [
        {"$match": {"study_id": study_id, "status": "terminated"}},
        {"$group": {"_id": "$termination_reason", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    term_reasons = []
    async for doc in db.respondents.aggregate(term_pipeline):
        term_reasons.append({"reason": doc["_id"], "count": doc["count"]})

    target = study["quotas"].get("total_sample", 500)
    return {
        "project_name": study["name"],
        "client_name": study.get("client_name", ""),
        "wave_label": next((w["label"] for w in study.get("waves", []) if w["wave_id"] == study.get("active_wave_id")), ""),
        "target_sample": target,
        "total_started": total,
        "completed": completed,
        "terminated": terminated,
        "in_progress": in_progress,
        "completion_rate": round(completed / total * 100, 1) if total > 0 else 0,
        "incidence_rate": round(completed / (completed + terminated) * 100, 1) if (completed + terminated) > 0 else 0,
        "fieldwork_progress": round(completed / target * 100, 1) if target > 0 else 0,
        "quota_summary": quota_summary,
        "daily_completions": daily,
        "termination_reasons": term_reasons,
    }
