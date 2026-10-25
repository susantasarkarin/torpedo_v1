"""Does the SFW respondent score predict client rejections? (owner, 2026-10-25)

Ground truth is the client's reconciliation (routers/traffic.py upload ->
clientRejected on url_parameters, client_rejects). Only completes in surveys
that HAVE a reconciliation upload are counted, otherwise "not rejected" just
means "not reconciled yet".

Per flag and per band: completes, rejected, rejection rate and lift over the
baseline rate. A flag is worth enforcing only when its lift is clearly above 1
on enough completes (MIN_SUPPORT); the report says which. Per vendor: the
rejection rate that feeds the vendor scorecard. Read-only on traffic data; the
report is stored in traffic_flow_db.quality_validation.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

MIN_SUPPORT = 30          # completes carrying a flag before its lift means anything
ENFORCE_LIFT = 2.0        # rejected at least twice as often as the baseline


def summarize(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """rows: completes with sfwFlags / sfwBand / vendorId / clientRejected."""
    total = rejected = 0
    by_flag = defaultdict(lambda: [0, 0])
    by_band = defaultdict(lambda: [0, 0])
    by_vendor = defaultdict(lambda: [0, 0])
    for r in rows:
        rej = bool(r.get("clientRejected"))
        total += 1
        rejected += rej
        for f in set(r.get("sfwFlags") or []):
            by_flag[f][0] += 1
            by_flag[f][1] += rej
        b = r.get("sfwBand") or "unscored"
        by_band[b][0] += 1
        by_band[b][1] += rej
        v = str(r.get("vendorId") or r.get("traffic_source") or "unknown")
        by_vendor[v][0] += 1
        by_vendor[v][1] += rej
    base = rejected / total if total else None

    def row(n, k):
        rate = k / n if n else None
        lift = (rate / base) if (rate is not None and base) else None
        return {"completes": n, "rejected": k, "rejection_rate": round(rate, 4) if rate is not None else None,
                "lift": round(lift, 2) if lift is not None else None}
    flags = {f: {**row(n, k), "enforce_candidate": bool(n >= MIN_SUPPORT and base and (k / n) / base >= ENFORCE_LIFT)}
             for f, (n, k) in by_flag.items()}
    return {"completes": total, "rejected": rejected, "baseline_rejection_rate": round(base, 4) if base is not None else None,
            "by_flag": dict(sorted(flags.items(), key=lambda kv: -(kv[1]["lift"] or 0))),
            "by_band": {b: row(n, k) for b, (n, k) in by_band.items()},
            "by_vendor": dict(sorted(((v, row(n, k)) for v, (n, k) in by_vendor.items()), key=lambda kv: -kv[1]["completes"]))}


def run(db, days: int = 180, now: Optional[datetime] = None) -> Dict[str, Any]:
    """db = traffic_flow_db (sync). Writes and returns the report."""
    from database import COL_URL_PARAMETERS
    now = now or datetime.utcnow()
    reconciled = db["client_reject_batches"].distinct("surveyNo", {"uploadedAt": {"$gte": now - timedelta(days=days)}})
    rows = db[COL_URL_PARAMETERS].find(
        {"status": "COMPLETE", "assignedSurveyId": {"$in": reconciled}},
        {"sfwFlags": 1, "sfwBand": 1, "vendorId": 1, "traffic_source": 1, "clientRejected": 1}) if reconciled else []
    rep = summarize(rows)
    scored = db[COL_URL_PARAMETERS].count_documents({"status": "COMPLETE", "sfwBand": {"$exists": True},
                                                     "completedAt": {"$gte": now - timedelta(days=days)}})
    rep.update(at=now, window_days=days, reconciled_surveys=len(reconciled), scored_completes_in_window=scored,
               note=None if reconciled else "no client reconciliation uploaded yet: nothing to validate the score against")
    db["quality_validation"].insert_one(dict(rep))
    return rep
