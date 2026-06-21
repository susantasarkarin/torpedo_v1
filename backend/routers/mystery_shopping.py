from fastapi import APIRouter, Request, HTTPException, Body, Query
from fastapi.responses import StreamingResponse
from typing import Dict, Any
from datetime import datetime, timezone
from bson import ObjectId
import os, io, csv
from motor.motor_asyncio import AsyncIOMotorClient

router = APIRouter(prefix="/api/mystery-shopping", tags=["Mystery Shopping"])

_MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
_client = AsyncIOMotorClient(_MONGO_URI)
_col = _client["operations_db"]["mystery_shopping_audits"]


def _serialize(doc):
    if doc is None:
        return None
    doc["id"] = str(doc.pop("_id"))
    return doc


def _require_auth(request: Request):
    session_id = request.headers.get("Authorization")
    if not session_id:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/audits")
async def list_audits(request: Request):
    _require_auth(request)
    audits = []
    async for doc in _col.find().sort("created_at", -1).limit(500):
        audits.append(_serialize(doc))
    return audits


@router.post("/audits")
async def create_audit(request: Request, payload: Dict[str, Any] = Body(...)):
    _require_auth(request)
    now = datetime.now(timezone.utc).isoformat()
    doc = {**payload, "status": payload.get("status", "draft"), "created_at": now, "updated_at": now}
    result = await _col.insert_one(doc)
    created = await _col.find_one({"_id": result.inserted_id})
    return _serialize(created)


@router.get("/audits/{audit_id}")
async def get_audit(audit_id: str, request: Request):
    _require_auth(request)
    try:
        doc = await _col.find_one({"_id": ObjectId(audit_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid audit ID")
    if not doc:
        raise HTTPException(status_code=404, detail="Audit not found")
    return _serialize(doc)


@router.put("/audits/{audit_id}")
async def update_audit(audit_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    _require_auth(request)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        await _col.update_one({"_id": ObjectId(audit_id)}, {"$set": payload})
        doc = await _col.find_one({"_id": ObjectId(audit_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid audit ID")
    if not doc:
        raise HTTPException(status_code=404, detail="Audit not found")
    return _serialize(doc)


@router.delete("/audits/{audit_id}")
async def delete_audit(audit_id: str, request: Request):
    _require_auth(request)
    try:
        result = await _col.delete_one({"_id": ObjectId(audit_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid audit ID")
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Audit not found")
    return {"ok": True}


# ── Questionnaire schema (mirrors frontend) ───────────────────────────────────
_SECTIONS = [
    ("A1", "External and Branch Appearance", ["a1_1","a1_2","a1_3","a1_4"], [
        "Signage — Branch and ATM signage is clean, fully illuminated, and clearly visible from the road.",
        "ATM Lobby — ATM lobby is clean, all machines are functional, and receipt paper is available.",
        "Entrance — Glass doors are clean and clear; correct operating hours are displayed at the entrance.",
        "Interior Cleanliness — Floors are spotless, counters are tidy, and brochure racks are organised.",
    ]),
    ("A2", "Guard and Welcome Desk", ["a2_1","a2_2","a2_3"], [
        "Security Guard — Guard is alert, properly uniformed, and greets customers appropriately.",
        "Welcome Desk — Welcome desk is attended by staff ready to direct customer traffic.",
        "Queue Management — Token / queue machine is working and the waiting time is reasonable.",
    ]),
    ("A3", "Staff Grooming and Behaviour", ["a3_1","a3_2","a3_3","a3_4"], [
        "Dress Code — Staff wear professional attire with visible ID / name badges.",
        "Body Language — Staff are attentive, make eye contact, and smile.",
        "Greeting — Staff greet politely using a standard opening phrase.",
        "Cell Phone Use — Staff are not using personal mobile phones in public view.",
    ]),
    ("A4", "Counter and Teller Services", ["a4_1","a4_2","a4_3","a4_4"], [
        "Efficiency — Cash handling is smooth and processing times are quick.",
        "Accuracy — Note-counting machines are used and correct denominations are given.",
        "Privacy — Account balances are not spoken aloud or made visible to others.",
        "Closing — Teller thanks the customer and offers further assistance.",
    ]),
    ("A5", "Branch Manager and Desk Operations", ["a5_1","a5_2","a5_3"], [
        "Availability — Branch Manager is visible or accessible in their cabin.",
        "Query Resolution — Staff are knowledgeable about accounts, loans, and interest rates.",
        "Tone — Staff are patient and helpful, especially when handling complex issues.",
    ]),
    ("A6", "Compliance and Customer Comfort", ["a6_1","a6_2","a6_3"], [
        "Mandatory Displays — Interest-rate charts and grievance / redressal notices are displayed.",
        "Seating — Adequate seating is available for waiting customers.",
        "Environment — Air conditioning is comfortable and drinking-water stations are functional.",
    ]),
    ("B1", "First Impression and Initial Inquiry", ["b1_1","b1_2","b1_3","b1_4"], [
        'Signage — Clear directions or desk counters are marked "Loans" or "Retail Assets".',
        "Initial Greeting — Staff acknowledge you promptly when you approach the loan desk.",
        "Wait Time — Time taken to speak with a dedicated loan officer is under 10 minutes.",
        "Privacy — Consultation takes place in a private booth or cabin, keeping details secure.",
    ]),
    ("B2", "Loan Officer Professionalism and Behaviour", ["b2_1","b2_2","b2_3","b2_4"], [
        "Active Listening — Officer asks about your income, employment, and funding needs before pitching.",
        "Expert Knowledge — Officer confidently explains different loan types (e.g., fixed vs floating rates).",
        "Product Pitching — Officer recommends a specific loan product that fits your stated needs.",
        "Tone — Officer is professional, welcoming, non-judgmental, and patient with questions.",
    ]),
    ("B3", "Transparency and Information Gathering", ["b3_1","b3_2","b3_3","b3_4"], [
        "Rate Disclosure — Officer clearly states the current interest rate and whether it is negotiable.",
        "Fee Breakdown — Processing fees, documentation charges, and prepayment penalties are explained.",
        "Turnaround Time (TAT) — A clear timeline is provided for loan approval and final disbursement.",
        "Eligibility Check — Officer explains the minimum credit score and income criteria needed.",
    ]),
    ("B4", "Documentation and Next Steps", ["b4_1","b4_2","b4_3","b4_4"], [
        "Checklist Provided — A clear printed or digital list of required documents is given to you.",
        "Digital Alternatives — Staff mention uploading documents online via the bank app or portal.",
        "Follow-up Capture — Officer asks for your contact details to follow up on the discussion.",
        "Closing — You are handed a business card and thanked politely for your time.",
    ]),
]
_SCORE_MAP = {"Yes": 5, "Partial": 3, "No": 0}
_SECTION_MAX = {"A1":20,"A2":15,"A3":20,"A4":20,"A5":15,"A6":15,"B1":20,"B2":20,"B3":20,"B4":20}


@router.get("/audits/{audit_id}/export")
async def export_audit(audit_id: str, request: Request, format: str = Query("csv")):
    _require_auth(request)
    try:
        doc = await _col.find_one({"_id": ObjectId(audit_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid audit ID")
    if not doc:
        raise HTTPException(status_code=404, detail="Audit not found")

    vd = doc.get("visit_details", {})
    responses = doc.get("responses", {})
    obs = doc.get("observations", {})

    # Build flat rows: section_id, section_name, #, parameter, response, score, remarks
    param_rows = []
    for sec_id, sec_name, param_ids, param_texts in _SECTIONS:
        for i, (pid, ptxt) in enumerate(zip(param_ids, param_texts), 1):
            r = responses.get(pid, {})
            resp = r.get("response", "")
            score = _SCORE_MAP.get(resp, "N/A" if resp == "N/A" else "")
            param_rows.append({
                "Section": f"{sec_id}. {sec_name}", "#": i,
                "Parameter": ptxt, "Response": resp,
                "Score": score, "Remarks": r.get("remarks", ""),
            })

    # Score summary rows
    score_rows = []
    for sec_id, sec_name, param_ids, _ in _SECTIONS:
        total, max_s = 0, 0
        for pid in param_ids:
            r = responses.get(pid, {})
            resp = r.get("response", "")
            if resp and resp != "N/A":
                max_s += 5
                total += _SCORE_MAP.get(resp, 0)
        pct = round(total / max_s * 100) if max_s else None
        score_rows.append({
            "Section": f"{sec_id}. {sec_name}",
            "Max Score": _SECTION_MAX.get(sec_id, max_s),
            "Score Achieved": total,
            "% Achieved": f"{pct}%" if pct is not None else "—",
        })

    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)

        # Visit details block
        w.writerow(["VISIT DETAILS"])
        for k, v in [
            ("Branch Name", vd.get("branch_name","")), ("Branch Code", vd.get("branch_code","")),
            ("Branch Address", vd.get("branch_address","")), ("City / State", vd.get("city_state","")),
            ("Region / Zone", vd.get("region_zone","")), ("Date of Visit", vd.get("date_of_visit","")),
            ("Time In", vd.get("time_in","")), ("Time Out", vd.get("time_out","")),
            ("Mystery Shopper Name", vd.get("shopper_name","")), ("Shopper ID", vd.get("shopper_id","")),
            ("Type of Visit", vd.get("type_of_visit","")), ("Scenario Used", vd.get("scenario_used","")),
            ("Staff Interacted With", vd.get("staff_interacted","")),
            ("Contact No. Collected", vd.get("contact_collected","")),
            ("Status", doc.get("status","")),
        ]:
            w.writerow([k, v])
        w.writerow([])

        # Questionnaire responses
        w.writerow(["QUESTIONNAIRE RESPONSES"])
        w.writerow(["Section", "#", "Parameter", "Response", "Score", "Remarks"])
        for r in param_rows:
            w.writerow([r["Section"], r["#"], r["Parameter"], r["Response"], r["Score"], r["Remarks"]])
        w.writerow([])

        # Score summary
        w.writerow(["SCORE SUMMARY"])
        w.writerow(["Section", "Max Score", "Score Achieved", "% Achieved"])
        for r in score_rows:
            w.writerow([r["Section"], r["Max Score"], r["Score Achieved"], r["% Achieved"]])
        w.writerow([])

        # Observations
        w.writerow(["OVERALL OBSERVATIONS"])
        w.writerow(["Key Strengths", obs.get("strengths", "")])
        w.writerow(["Areas Needing Improvement", obs.get("improvements", "")])
        w.writerow(["Specific Recommendations", obs.get("recommendations", "")])

        branch = (vd.get("branch_name") or "audit").replace(" ", "_")[:40]
        filename = f"ms_audit_{branch}_{audit_id[:8]}.csv"
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    elif format == "spss":
        try:
            import pyreadstat, pandas as pd, tempfile, pathlib
            rows = []
            for r in param_rows:
                rows.append({
                    "section": r["Section"], "param_num": r["#"],
                    "parameter": r["Parameter"][:64],
                    "response": r["Response"],
                    "score": r["Score"] if isinstance(r["Score"], int) else -1,
                    "remarks": r["Remarks"],
                })
            df = pd.DataFrame(rows)
            tmp = tempfile.NamedTemporaryFile(suffix=".sav", delete=False)
            tmp.close()
            pyreadstat.write_sav(df, tmp.name)
            data = pathlib.Path(tmp.name).read_bytes()
            pathlib.Path(tmp.name).unlink(missing_ok=True)
            branch = (vd.get("branch_name") or "audit").replace(" ", "_")[:40]
            filename = f"ms_audit_{branch}_{audit_id[:8]}.sav"
            return StreamingResponse(
                iter([data]),
                media_type="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"SPSS export failed: {e}")

    raise HTTPException(status_code=400, detail="format must be 'csv' or 'spss'")


# ── Public endpoints (no auth — accessed by field shoppers via live link) ─────

@router.get("/public/{audit_id}")
async def get_audit_public(audit_id: str):
    try:
        doc = await _col.find_one({"_id": ObjectId(audit_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid audit ID")
    if not doc:
        raise HTTPException(status_code=404, detail="Audit not found")
    return _serialize(doc)


@router.put("/public/{audit_id}/submit")
async def field_submit(audit_id: str, payload: Dict[str, Any] = Body(...)):
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload.setdefault("status", "submitted")
    try:
        await _col.update_one({"_id": ObjectId(audit_id)}, {"$set": payload})
        doc = await _col.find_one({"_id": ObjectId(audit_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid audit ID")
    if not doc:
        raise HTTPException(status_code=404, detail="Audit not found")
    return _serialize(doc)
