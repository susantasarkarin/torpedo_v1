"""
Study & Wave CRUD — manages multiple studies/clients and tracking waves.
Each study has its own quotas, respondents, redirects, and module config.
Waves allow brands and ad stimuli to change between fieldwork periods.
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter(prefix="/api/studies", tags=["studies"])


def _db():
    from main import db
    return db


# ---------- Default module configs (template for new studies) ----------

DEFAULT_MODULES = [
    {"num": 1, "startQ": 29, "name": "Pain & Fever Relief",
     "brands": ["Crocin", "Dolo 650", "Combiflam", "Saridon", "Disprin", "Calpol",
                 "Meftal-Spas", "Brufen", "Zerodol-SP", "Sumo", "Dart", "Metacin"],
     "focalBrand": "Dolo 650", "focalStatement": "Dolo 650 is a trusted and effective pain reliever",
     "priceLabel": "₹30 per strip of 15 tablets"},
    {"num": 2, "startQ": 37, "name": "Vitamins & Supplements",
     "brands": ["Becosules", "Revital H", "Supradyn", "Zincovit", "Limcee", "Shelcal",
                 "Neurobion Forte", "Evion", "A to Z NS", "Becosules Z", "Celin", "Nature Made"],
     "focalBrand": "Revital H", "focalStatement": "Revital H provides daily energy and immunity",
     "priceLabel": "₹350 for 30 capsules"},
    {"num": 3, "startQ": 45, "name": "Cold, Cough & Flu",
     "brands": ["Vicks Action 500", "Benadryl", "Strepsils", "Sinarest", "D'Cold Total",
                 "Chericof", "Honitus", "Otrivin", "Mucinex", "Tixylix", "Alex", "Cofsils"],
     "focalBrand": "Vicks Action 500", "focalStatement": "Vicks Action 500 gives fast relief from cold & flu",
     "priceLabel": "₹25 per strip"},
    {"num": 4, "startQ": 53, "name": "Antacids & Digestive",
     "brands": ["Digene", "Eno", "Gelusil", "Pudin Hara", "Gas-O-Fast", "Pan-D",
                 "Pantocid", "Ranitidine", "Aciloc", "Mucaine", "Gaviscon", "Kremil-S"],
     "focalBrand": "Eno", "focalStatement": "Eno provides instant relief from acidity",
     "priceLabel": "₹10 per sachet"},
    {"num": 5, "startQ": 61, "name": "Allergy & Antihistamines",
     "brands": ["Allegra", "Zyrtec", "Avil", "Cetrizine", "Montair-LC", "Levocet",
                 "Okacet", "Levocetirizine", "Fexofenadine", "Bilastine", "Xyzal", "Sinarest"],
     "focalBrand": "Allegra", "focalStatement": "Allegra is the most prescribed allergy relief brand",
     "priceLabel": "₹150 for 10 tablets"},
    {"num": 6, "startQ": 69, "name": "Antiseptics & First Aid",
     "brands": ["Dettol", "Savlon", "Betadine", "Burnol", "Soframycin", "Band-Aid",
                 "Hansaplast", "Neosporin", "T-Bact", "Boroline", "Zandu Balm", "Boroplus"],
     "focalBrand": "Dettol", "focalStatement": "Dettol is the most trusted antiseptic brand in India",
     "priceLabel": "₹55 for 125ml liquid"},
    {"num": 7, "startQ": 77, "name": "Antifungal & Skin",
     "brands": ["Candid", "Ring Guard", "Itch Guard", "Clocip", "Terbinafine", "Luliconazole",
                 "Clotrimazole", "Candid-B", "Betnovate", "Fourderm", "Panderm", "Quadriderm"],
     "focalBrand": "Ring Guard", "focalStatement": "Ring Guard is trusted for ringworm and fungal care",
     "priceLabel": "₹80 per tube"},
    {"num": 8, "startQ": 85, "name": "Eye & Ear Drops",
     "brands": ["Refresh Tears", "Systane", "Visine", "Genteal", "I-Tone", "Itone",
                 "Moxiflox", "Ciplox Eye", "Patanol", "Waxolve", "Soliwax", "Otogesic"],
     "focalBrand": "Refresh Tears", "focalStatement": "Refresh Tears provides lasting dry eye relief",
     "priceLabel": "₹180 per bottle"},
    {"num": 9, "startQ": 93, "name": "Oral Care",
     "brands": ["Sensodyne", "Colgate Sensitive", "Parodontax", "Listerine", "Betadine Gargle",
                 "Hexidine", "Dentogel", "Orajel", "Clohex", "Meswak", "Dabur Red", "Himalaya Gum Care"],
     "focalBrand": "Sensodyne", "focalStatement": "Sensodyne provides clinically proven sensitivity relief",
     "priceLabel": "₹120 for 70g tube"},
    {"num": 10, "startQ": 101, "name": "Anti-Diarrheal & ORS",
     "brands": ["Electral", "Pedialyte", "Imodium", "Redotil", "Racecadotril", "Norflox-TZ",
                 "Oflox-OZ", "Econorm", "Enterogermina", "Bifilac", "Darolac", "Sporlac"],
     "focalBrand": "Electral", "focalStatement": "Electral is India's most recommended ORS",
     "priceLabel": "₹22 per sachet"},
    {"num": 11, "startQ": 109, "name": "Herbal / Ayurvedic OTC",
     "brands": ["Dabur Chyawanprash", "Himalaya Liv.52", "Baidyanath", "Zandu Pancharishta",
                 "Hamdard Rooh Afza", "Patanjali Coronil", "Ashwagandha", "Triphala",
                 "Brahmi", "Shatavari", "Giloy", "Tulsi drops"],
     "focalBrand": "Himalaya Liv.52", "focalStatement": "Himalaya Liv.52 is the world's #1 liver care brand",
     "priceLabel": "₹135 for 100 tablets"},
    {"num": 12, "startQ": 117, "name": "Maternal & Child Nutrition",
     "brands": ["Nestlé NAN", "Similac", "Aptamil", "Cerelac", "Dexolac", "Farex",
                 "PediaSure", "Junior Horlicks", "Bournvita", "Enfagrow", "Lactogen", "Nan Pro"],
     "focalBrand": "PediaSure", "focalStatement": "PediaSure supports complete balanced nutrition for children",
     "priceLabel": "₹750 for 400g"},
    {"num": 13, "startQ": 125, "name": "Diagnostics & Lab Testing",
     "brands": ["Dr. Lal PathLabs", "Metropolis", "SRL Diagnostics", "Thyrocare", "Redcliffe Labs",
                 "Apollo Diagnostics", "Suburban Diagnostics", "Healthians", "1mg Labs",
                 "Pharmeasy Labs", "Orange Health", "Tata 1mg Labs"],
     "focalBrand": "Dr. Lal PathLabs", "focalStatement": "Dr. Lal PathLabs is India's leading diagnostics chain",
     "priceLabel": "₹500 for basic health checkup"},
    {"num": 14, "startQ": 133, "name": "Digital Health & Telemedicine",
     "brands": ["Practo", "Tata 1mg", "PharmEasy", "Netmeds", "MediBuddy", "DocsApp",
                 "mFine", "Lybrate", "Apollo 24/7", "Bajaj Health", "Cult.fit Health", "Pristyn Care"],
     "focalBrand": "Practo", "focalStatement": "Practo is the most trusted digital health platform",
     "priceLabel": "₹299 per consultation"},
    {"num": 15, "startQ": 141, "name": "Wearables & Health Devices",
     "brands": ["Apple Watch", "Fitbit", "Garmin", "Samsung Galaxy Watch", "Noise",
                 "boAt Watch", "Fire-Boltt", "Titan Smart", "Omron BP Monitor",
                 "Accu-Chek", "Dr. Trust", "Beurer"],
     "focalBrand": "Noise", "focalStatement": "Noise smartwatches deliver health tracking at great value",
     "priceLabel": "₹2,499"},
    {"num": 16, "startQ": 149, "name": "Hospital Brand Equity",
     "brands": ["Apollo Hospitals", "Fortis", "Max Healthcare", "Manipal Hospitals", "Narayana Health",
                 "Medanta", "AIIMS", "Aster DM", "Columbia Asia", "Kokilaben Ambani", "Hinduja", "Lilavati"],
     "focalBrand": "Apollo Hospitals", "focalStatement": "Apollo is a pioneer and leader in Indian healthcare",
     "priceLabel": "₹500 for OPD consultation"},
    {"num": 17, "startQ": 157, "name": "Health Insurance",
     "brands": ["Star Health", "Niva Bupa", "Care Health", "HDFC Ergo Health", "ICICI Lombard Health",
                 "Bajaj Allianz Health", "Max Bupa", "Aditya Birla Health", "New India Assurance",
                 "ManipalCigna", "Tata AIG Health", "Digit Health"],
     "focalBrand": "Star Health", "focalStatement": "Star Health is India's largest standalone health insurer",
     "priceLabel": "₹700/month family floater"},
    {"num": 18, "startQ": 165, "name": "Fitness & Sports Nutrition",
     "brands": ["MuscleBlaze", "Optimum Nutrition", "GNC", "Fast&Up", "Oziva Protein",
                 "Myprotein", "Herbalife", "Amway Nutrilite", "Avvatar", "Nakpro",
                 "AS-IT-IS", "Big Muscles"],
     "focalBrand": "MuscleBlaze", "focalStatement": "MuscleBlaze is India's #1 sports nutrition brand",
     "priceLabel": "₹2,199 for 1kg whey"},
    {"num": 19, "startQ": 173, "name": "Mental Health Services",
     "brands": ["YourDOST", "Wysa", "iCall", "Vandrevala Foundation", "BetterHelp India",
                 "Amaha", "InnerHour", "Mindpeers", "Tele-MANAS", "Lissun", "MindPeers", "Cult.fit Mind"],
     "focalBrand": "Wysa", "focalStatement": "Wysa AI coach for mental health is clinically validated",
     "priceLabel": "₹3,000/month premium"},
    {"num": 20, "startQ": 181, "name": "Dental & Vision Care",
     "brands": ["Lenskart", "Clove Dental", "Titan Eye Plus", "GKB Opticals", "Lawrence & Mayo",
                 "Specsmakers", "Vision Express", "Centre for Sight", "ASG Eye Hospital",
                 "Dr Agarwal's Eye Hospital", "Sabka Dentist", "MyDentist"],
     "focalBrand": "Lenskart", "focalStatement": "Lenskart has revolutionized eyewear shopping in India",
     "priceLabel": "₹1,500 for progressive lenses"},
    {"num": 21, "startQ": 189, "name": "D2C Health & Wellness",
     "brands": ["Oziva", "Kapiva", "Dr. Vaidya's", "Nirvasa", "Plix", "Wellbeing Nutrition",
                 "Man Matters", "Be Bodywise", "Traya", "SkinKraft", "Vedistry", "HealthKart"],
     "focalBrand": "Oziva", "focalStatement": "Oziva is India's leading plant-based nutrition brand",
     "priceLabel": "₹799 for 30-day pack"},
]

DEFAULT_AD_STIMULI = [
    {"slot": 1, "label": "Ad Creative A", "url": "", "min_view_seconds": 5},
    {"slot": 2, "label": "Ad Creative B", "url": "", "min_view_seconds": 5},
]

DEFAULT_QUOTAS = {
    "total_sample": 500,
    "cells": {
        "band1_25_34": 170, "band2_35_44": 165, "band3_45_55": 165,
        "male": 225, "female": 275,
        "nccs_a": 250, "nccs_b": 250,
        "chennai": 125, "kolkata": 125, "mumbai": 125, "hyderabad": 125,
    }
}


# ---------- Pydantic models ----------

class StudyCreate(BaseModel):
    name: str
    client_name: str
    description: str = ""

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

    wave_1 = {
        "wave_id": "w1",
        "label": "Wave 1",
        "modules": [dict(m) for m in DEFAULT_MODULES],
        "ad_stimuli": [dict(a) for a in DEFAULT_AD_STIMULI],
        "created_at": now,
        "status": "active",
    }

    study_doc = {
        "_id": study_id,
        "name": payload.name,
        "client_name": payload.client_name,
        "description": payload.description,
        "status": "draft",  # draft | live | paused | closed
        "created_at": now,
        "updated_at": now,
        "active_wave_id": "w1",
        "waves": [wave_1],
        "quotas": dict(DEFAULT_QUOTAS),
        "redirects": {"complete_url": "", "terminate_url": "", "overquota_url": ""},
    }

    await db.studies.insert_one(study_doc)

    # Create scoped quota counter doc
    cells = {k: 0 for k in DEFAULT_QUOTAS["cells"]}
    cells["_id"] = f"quota_{study_id}"
    await db.quotas.insert_one(cells)

    return {"id": study_id, "name": payload.name}


@router.get("/{study_id}")
async def get_study(study_id: str):
    """Get full study config including current wave."""
    db = _db()
    doc = await db.studies.find_one({"_id": study_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Study not found")
    doc["id"] = doc.pop("_id")
    return doc


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
    """Get quota status for a study."""
    db = _db()
    study = await db.studies.find_one({"_id": study_id}, {"quotas": 1})
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    counter_doc = await db.quotas.find_one({"_id": f"quota_{study_id}"}) or {}
    limits = study["quotas"]["cells"]
    result = []
    for key, limit in limits.items():
        current = counter_doc.get(key, 0)
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
    """Create a new wave — copies modules from previous wave or uses defaults."""
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
    }


@router.get("/{study_id}/export")
async def export_study_csv(study_id: str, status_filter: str = "completed"):
    """Export study responses as CSV. status_filter: completed | all"""
    import io, csv
    from fastapi.responses import StreamingResponse

    db = _db()
    query = {"study_id": study_id}
    if status_filter == "completed":
        query["status"] = "completed"

    cursor = db.respondents.find(query)
    rows = []
    all_q_ids = set()
    async for doc in cursor:
        resp = doc.get("responses", {})
        all_q_ids.update(resp.keys())
        row = {
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
        for qid, val in resp.items():
            row[qid] = ";".join(str(v) for v in val) if isinstance(val, list) else str(val)
        rows.append(row)

    if not rows:
        return {"message": "No responses to export"}

    sorted_q_ids = sorted(all_q_ids, key=lambda x: int(x.replace("Q", "")) if x.replace("Q", "").isdigit() else 0)
    output = io.StringIO()
    meta = ["respondent_id", "study_id", "wave_id", "status", "termination_reason",
            "nccs_grade", "nccs_band", "assigned_modules", "started_at", "completed_at"]
    writer = csv.DictWriter(output, fieldnames=meta + sorted_q_ids, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    output.seek(0)
    study = await db.studies.find_one({"_id": study_id}, {"name": 1})
    fname = (study["name"] if study else study_id).replace(" ", "_").lower()
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}_{status_filter}.csv"},
    )


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

    # Quota fill
    counter_doc = await db.quotas.find_one({"_id": f"quota_{study_id}"}) or {}
    limits = study["quotas"]["cells"]
    quota_summary = []
    for key, limit in limits.items():
        current = counter_doc.get(key, 0)
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
