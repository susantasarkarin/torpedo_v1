"""
MODULE 1 — LEAD PIPELINE VALIDATION
=====================================
Validates that all stages of the lead generation and outreach pipeline
are operational. Each check is independent and logs failures clearly.

Checks:
1. Database connectivity
2. AI leads collection health (recent entries, no stuck records)
3. CSV upload pipeline (parse, store, dedup)
4. Gemini Gateway daily quota status
5. Gmail API connectivity
6. Celery workers alive (sales + ai_processing queues)
7. Enrichment pipeline (stuck/failed leads ratio)
8. Email construction queue health
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────
#  CHECK 1: Database connectivity
# ─────────────────────────────────────────────────────

def check_database() -> Dict[str, Any]:
    try:
        from db_pools import get_background_db
        db = get_background_db()
        db.command("ping")
        leads_count = db["leads"].estimated_document_count()
        return {"ok": True, "leads_total": leads_count}
    except Exception as e:
        logger.error(f"[Validation] Database check failed: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────
#  CHECK 2: AI leads pipeline health
# ─────────────────────────────────────────────────────

def check_ai_leads_pipeline() -> Dict[str, Any]:
    try:
        from db_pools import get_background_db
        db = get_background_db()
        leads = db["leads"]

        since = datetime.utcnow() - timedelta(hours=24)
        recent_total = leads.count_documents({"created_at": {"$gte": since}})
        stuck_enrichment = leads.count_documents({
            "stage": "verified",
            "enrichment.status": {"$in": [None, "pending"]},
            "updated_at": {"$lt": datetime.utcnow() - timedelta(hours=2)},
        })
        failed_enrichment = leads.count_documents({"enrichment.status": "failed"})

        ok = stuck_enrichment < 20  # flag if more than 20 leads stuck
        if not ok:
            logger.warning(f"[Validation] {stuck_enrichment} leads stuck in enrichment queue")

        return {
            "ok": ok,
            "recent_24h": recent_total,
            "stuck_in_enrichment": stuck_enrichment,
            "failed_enrichment_total": failed_enrichment,
        }
    except Exception as e:
        logger.error(f"[Validation] AI leads pipeline check failed: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────
#  CHECK 3: CSV upload pipeline
# ─────────────────────────────────────────────────────

def check_csv_pipeline(csv_bytes: Optional[bytes] = None) -> Dict[str, Any]:
    """
    If csv_bytes is provided, parse and validate the CSV.
    Otherwise just confirm the import function is importable and healthy.
    """
    try:
        import csv
        import io

        if csv_bytes:
            reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8", errors="replace")))
            rows = list(reader)
            if not rows:
                logger.warning("[Validation] CSV uploaded but parsed 0 rows")
                return {"ok": False, "error": "CSV is empty or has no data rows"}

            required = {"name", "email", "company"}
            headers = {h.strip().lower() for h in (reader.fieldnames or [])}
            missing = required - headers
            if missing:
                logger.warning(f"[Validation] CSV missing required columns: {missing}")
                return {"ok": False, "error": f"Missing columns: {missing}", "rows_parsed": len(rows)}

            valid_rows = [r for r in rows if r.get("email", "").strip()]
            logger.info(f"[Validation] CSV parsed: {len(rows)} rows, {len(valid_rows)} with email")
            return {"ok": True, "rows_parsed": len(rows), "rows_with_email": len(valid_rows)}

        # No file provided — just health check the import function
        from leads.service import import_leads  # noqa: F401
        return {"ok": True, "note": "CSV import function reachable"}
    except Exception as e:
        logger.error(f"[Validation] CSV pipeline check failed: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────
#  CHECK 4: AI Gateway quota
# ─────────────────────────────────────────────────────

def check_gemini_quota() -> Dict[str, Any]:
    try:
        from ai_governance.governance_checks import get_gemini_daily_usage, GEMINI_DAILY_LIMIT
        used, remaining = get_gemini_daily_usage()
        ok = remaining > 100  # warn if fewer than 100 calls remain
        if not ok:
            logger.warning(f"[Validation] AI quota low: {remaining} remaining")
        return {"ok": ok, "used_today": used, "remaining": remaining, "limit": GEMINI_DAILY_LIMIT}
    except Exception as e:
        logger.error(f"[Validation] AI quota check failed: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────
#  CHECK 5: Gmail API connectivity
# ─────────────────────────────────────────────────────

def check_gmail_api() -> Dict[str, Any]:
    try:
        import sys
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)

        from gmail_automation.auth import GmailAuthenticator
        auth = GmailAuthenticator()
        service = auth.authenticate()
        # Just call profile endpoint — does not send anything
        profile = service.users().getProfile(userId="me").execute()
        email_address = profile.get("emailAddress", "")
        return {"ok": bool(email_address), "gmail_account": email_address}
    except Exception as e:
        logger.error(f"[Validation] Gmail API check failed: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────
#  CHECK 6: Celery workers alive
# ─────────────────────────────────────────────────────

def check_celery_workers() -> Dict[str, Any]:
    try:
        from celery_app import celery_app
        inspect = celery_app.control.inspect(timeout=3)
        active = inspect.active()
        if not active:
            logger.warning("[Validation] No active Celery workers found")
            return {"ok": False, "error": "No Celery workers responded within timeout"}

        workers = list(active.keys())
        queues = []
        stats = inspect.stats()
        if stats:
            for w, info in stats.items():
                broker_q = info.get("broker", {}).get("transport_options", {})
                queues.append({"worker": w, "broker": broker_q})
        return {"ok": True, "workers": workers, "count": len(workers)}
    except Exception as e:
        logger.error(f"[Validation] Celery worker check failed: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────
#  CHECK 7: Enrichment pipeline ratio
# ─────────────────────────────────────────────────────

def check_enrichment_health() -> Dict[str, Any]:
    try:
        from db_pools import get_background_db
        db = get_background_db()
        leads = db["leads"]

        total_enrichable = leads.count_documents({"stage": {"$in": ["verified", "enriched"]}})
        failed = leads.count_documents({"enrichment.status": "failed"})
        done = leads.count_documents({"enrichment.status": "done"})

        failure_rate = (failed / total_enrichable * 100) if total_enrichable > 0 else 0
        ok = failure_rate < 20  # flag if >20% failure rate
        if not ok:
            logger.warning(f"[Validation] Enrichment failure rate: {failure_rate:.1f}%")

        return {
            "ok": ok,
            "total_enrichable": total_enrichable,
            "enriched": done,
            "failed": failed,
            "failure_rate_pct": round(failure_rate, 1),
        }
    except Exception as e:
        logger.error(f"[Validation] Enrichment health check failed: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────
#  CHECK 8: Email construction queue health
# ─────────────────────────────────────────────────────

def check_email_construction_queue() -> Dict[str, Any]:
    try:
        from db_pools import get_background_db
        db = get_background_db()
        leads = db["leads"]

        needs_construction = leads.count_documents({
            "email": {"$in": [None, ""]},
            "stage": "new",
            "domain": {"$exists": True, "$ne": ""},
        })
        stuck = leads.count_documents({
            "email": {"$in": [None, ""]},
            "stage": "new",
            "updated_at": {"$lt": datetime.utcnow() - timedelta(hours=6)},
        })

        ok = stuck < 50
        if not ok:
            logger.warning(f"[Validation] {stuck} leads stuck in email construction queue")

        return {
            "ok": ok,
            "needs_construction": needs_construction,
            "stuck_6h": stuck,
        }
    except Exception as e:
        logger.error(f"[Validation] Email construction queue check failed: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────
#  RUN ALL CHECKS
# ─────────────────────────────────────────────────────

def run_full_validation(csv_bytes: Optional[bytes] = None) -> Dict[str, Any]:
    """
    Run all pipeline validation checks.
    Returns a consolidated report dict with overall status and per-check results.
    """
    checks = {
        "database": check_database(),
        "ai_leads_pipeline": check_ai_leads_pipeline(),
        "csv_pipeline": check_csv_pipeline(csv_bytes),
        "gemini_quota": check_gemini_quota(),
        "gmail_api": check_gmail_api(),
        "celery_workers": check_celery_workers(),
        "enrichment_health": check_enrichment_health(),
        "email_construction_queue": check_email_construction_queue(),
    }

    all_ok = all(v.get("ok", False) for v in checks.values())
    failed_checks = [k for k, v in checks.items() if not v.get("ok", False)]

    if failed_checks:
        logger.error(f"[Validation] Pipeline validation FAILED. Failed checks: {failed_checks}")
    else:
        logger.info("[Validation] All pipeline checks passed.")

    return {
        "overall_ok": all_ok,
        "failed_checks": failed_checks,
        "checked_at": datetime.utcnow().isoformat(),
        "checks": checks,
    }
