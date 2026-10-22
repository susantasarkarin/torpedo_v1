"""
Project qualifications filled automatically from the RFQ email (2026-10-22).

Owner: "the qualification, if present in the mail should be automatically
filled. if not present then we should be able to fill in manually."

  when      a project is created or saved, and every 30 min for live / paused
            projects not filled yet (the RFQ email can arrive later); a project
            whose email has no target group is looked at again after 6 h -- each
            look scans the mail store (~4 s), too heavy to repeat every 30 min
  what      services/rfq_targeting.extract on the project's RFQ email: age range,
            women / men only, NCCS (India), cities, children; LOI and IR when
            the project has none
  never     overwrites a value that is already set, and stops for good once
            someone saves the project's Qualifications page
            (qualificationManual = true) -- from then on it is theirs
  record    qualificationSource = {from: "rfq_email", subject, at}; the
            previous values go to projects_qualification_backup_auto first
"""
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from bson import ObjectId

from services import rfq_targeting

RECHECK_HOURS = 6
AUTO_KEYS = ("genders", "nccs", "cities", "states", "childrenMin", "childAgeMin", "childAgeMax")
_CLIENT: Dict[str, Any] = {}


def _empty(v: Any) -> bool:
    return v in (None, "", [])


def _client():
    if "c" not in _CLIENT:
        from motor.motor_asyncio import AsyncIOMotorClient
        _CLIENT["c"] = AsyncIOMotorClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017")
    return _CLIENT["c"]


def merge(project: Dict[str, Any], found: Dict[str, Any]) -> Dict[str, Any]:
    """The $set for this project: only fields that are empty now. {} when nothing to fill."""
    fq = dict(found.get("qualification") or {})
    if str(project.get("countryCode") or "IN").strip().upper() not in ("IN", ""):
        fq.pop("nccs", None)  # NCCS is India only
    old = dict(project.get("qualification") or {})
    new = dict(old)
    if ("ageMin" in fq or "ageMax" in fq) and not new.get("ageRanges") \
            and _empty(new.get("ageMin")) and _empty(new.get("ageMax")):
        new["ageRanges"] = [{"min": fq.get("ageMin", ""), "max": fq.get("ageMax", "")}]
    for k in AUTO_KEYS:
        if k in fq and _empty(new.get(k)):
            new[k] = fq[k]
    sets: Dict[str, Any] = {}
    if new != old:
        new["enabled"] = True
        sets["qualification"] = new
    if found.get("loi") and _empty(project.get("loi")):
        sets["loi"] = str(found["loi"])
    if found.get("ir") and _empty(project.get("clientIR")):
        sets["clientIR"] = str(found["ir"])
    return sets


async def fill(project: Dict[str, Any], client=None) -> Optional[Dict[str, Any]]:
    """Fill one project from its RFQ email. Returns what was set, or None."""
    if project.get("qualificationManual") or project.get("is_deleted"):
        return None
    client = client if client is not None else _client()
    brief = await rfq_targeting.find_brief(client["torpedo_gmail"]["email_metadata"], project)
    sets = merge(project, rfq_targeting.extract(brief["text"])) if brief else {}
    if not sets:  # no email, or nothing in it to fill: look again after RECHECK_HOURS
        await client["email_automation"]["projects"].update_one(
            {"_id": project["_id"]}, {"$set": {"qualificationAutofillCheckedAt": datetime.utcnow()}})
        return None
    db = client["email_automation"]
    await db["projects_qualification_backup_auto"].insert_one({
        "projectId": project["_id"], "surveyNo": project.get("surveyNo"), "qualification": project.get("qualification"),
        "loi": project.get("loi"), "clientIR": project.get("clientIR"), "savedAt": datetime.utcnow()})
    sets["qualificationSource"] = {"from": "rfq_email", "subject": brief.get("subject"), "at": datetime.utcnow()}
    # never race a manual save: only while the project is still not manual
    await db["projects"].update_one({"_id": project["_id"], "qualificationManual": {"$ne": True}}, {"$set": sets})
    print(f"[qualifications] {project.get('surveyNo')} filled from RFQ email: {sorted(k for k in sets if k != 'qualificationSource')}")
    return sets


async def fill_by_id(project_id: str) -> Optional[Dict[str, Any]]:
    try:
        client = _client()
        project = await client["email_automation"]["projects"].find_one({"_id": ObjectId(str(project_id))})
        return await fill(project, client) if project else None
    except Exception as e:  # never fails the request that triggered it
        print(f"[warn] qualification auto-fill for {project_id} failed: {e}")
        return None


async def fill_open_projects(client=None) -> int:
    """Live and paused projects not under manual control. Returns how many were filled."""
    client = client if client is not None else _client()
    n = 0
    cursor = client["email_automation"]["projects"].find({
        "is_deleted": {"$ne": True}, "qualificationManual": {"$ne": True},
        "qualificationSource": {"$exists": False},          # filled once already: done
        "projectStatus": {"$regex": "^(live|pause)$", "$options": "i"},
        "$or": [{"qualificationAutofillCheckedAt": {"$exists": False}},
                {"qualificationAutofillCheckedAt": {"$lt": datetime.utcnow() - timedelta(hours=RECHECK_HOURS)}}]})
    async for project in cursor:
        try:
            if await fill(project, client):
                n += 1
        except Exception as e:
            print(f"[warn] qualification auto-fill for {project.get('surveyNo')} failed: {e}")
    return n


def run_job() -> None:
    """Scheduler entry (BackgroundScheduler thread): its own event loop and its own client."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _run():
        client = AsyncIOMotorClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017")
        try:
            return await fill_open_projects(client)
        finally:
            client.close()

    n = asyncio.run(_run())
    if n:
        print(f"[qualifications] auto-filled {n} project(s) from RFQ emails")
