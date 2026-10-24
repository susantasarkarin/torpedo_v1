"""Consolidated lead list as a spreadsheet (CRM plan 3.2.3). Login required.

GET /api/leads/export.xlsx?bucket=SFW|COGENTIX_RESEARCH|BIM|REVIEW|REJECT
One row per lead in email_automation.leads_raw with its company, domain, BU
bucket (+ confidence, reason, method) and email provenance.
"""
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from session_state import verify_session

router = APIRouter(prefix="/api/leads", tags=["leads"])

COLUMNS = [
    ("Name", "name"), ("Title", "title"), ("Company", "company"), ("Company domain", "company_domain"),
    ("Country", "country"), ("Email", "email"), ("Email source", "email_source"),
    ("Email pattern confidence", "email_pattern_confidence"), ("Email status", "email_status"),
    ("BU bucket", "outreach_bucket"), ("Bucket confidence", "outreach_bucket_confidence"),
    ("Bucket method", "outreach_bucket_method"), ("Bucket reason", "outreach_bucket_reason"),
    ("Source", "source"), ("Created", "created_at"),
]


def build_workbook(rows) -> bytes:
    from openpyxl import Workbook
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Leads")
    ws.append([c[0] for c in COLUMNS])
    for r in rows:
        out = []
        for _, field in COLUMNS:
            v = r.get(field)
            if field == "company" and not v:
                v = r.get("company_name")
            if isinstance(v, datetime):
                v = v.strftime("%Y-%m-%d %H:%M")
            elif v is not None and not isinstance(v, (int, float, str)):
                v = str(v)
            out.append(v)
        ws.append(out)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.get("/export.xlsx")
async def export_leads(bucket: Optional[str] = Query(None), user: str = Depends(verify_session)):
    from database import get_database
    q = {"outreach_bucket": bucket} if bucket else {}
    proj = {f: 1 for _, f in COLUMNS} | {"company_name": 1}
    rows = get_database("email_automation")["leads_raw"].find(q, proj).sort("created_at", -1)
    data = build_workbook(rows)
    name = f"leads_{bucket or 'all'}_{datetime.utcnow():%Y%m%d}.xlsx"
    try:
        from platform_core.audit import log_action
        log_action(actor=user, action="export", entity_type="lead_export", entity_id=name,
                   reason="lead list exported", metadata={"bucket": bucket})
    except Exception:
        pass
    return StreamingResponse(io.BytesIO(data),
                             media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
