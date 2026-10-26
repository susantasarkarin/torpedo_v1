"""Shared by the ad-platform integrations (MARKETING_PLAN 3.4): storing daily rows, INR conversion,
and the offline-conversion queue (3.4.4).

Offline conversions: per lead with a platform click ID (or a hashable email for Enhanced
Conversions / CAPI), one event each of
  lead            the CRM lead was created
  qualified_lead  the person replied or sent a business-domain form (not free webmail)
  rfq             an RFQ (opportunity) for that contact
  won             a won opportunity, value = invoiced / won INR (touchpoints.revenue_inr)
offline_conversion_uploads holds one row per (platform, lead, event): never sent twice.
Sending is shadow until action_modes["conversions:<platform>"] = "live" and mode = live.
"""
import hashlib
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional

from marketing import schema

EVENTS = ("lead", "qualified_lead", "rfq", "won")
FREE = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "icloud.com", "rediffmail.com", "yahoo.co.in"}


def fx(gd) -> Dict[str, float]:
    try:
        from kpi.compute import _fx
        return _fx(gd)
    except Exception:
        return {"INR": 1.0}


def to_inr(amount: float, currency: Optional[str], rates: Dict[str, float]) -> Optional[float]:
    r = rates.get((currency or "INR").upper())
    return round(float(amount or 0) * r, 2) if r else None


def sha256_email(email: str) -> Optional[str]:
    e = (email or "").strip().lower()
    if "@" not in e:
        return None
    local, dom = e.split("@", 1)
    if dom in ("gmail.com", "googlemail.com"):          # Google's normalisation for gmail addresses
        local = local.split("+", 1)[0].replace(".", "")
    return hashlib.sha256(f"{local}@{dom}".encode()).hexdigest()


def sha256_phone(phone: str) -> Optional[str]:
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 10:
        d = "91" + d
    return hashlib.sha256(d.encode()).hexdigest() if len(d) >= 11 else None


def store_metrics(gd: Callable, platform: str, rows: Iterable[Dict[str, Any]], *, now: datetime) -> int:
    """rows: {level, entity_id, date, name, campaign_id, group_id, bu, spend_inr, impressions, clicks, conversions, leads,
    frequency, ...}. Idempotent per (platform, level, entity_id, date)."""
    from pymongo import UpdateOne
    ops = []
    for r in rows:
        r = dict(r, platform=platform)
        bu = r.get("bu") if r.get("bu") in schema.BUS else None
        ops.append(UpdateOne(*schema.upsert_ops(r, ["platform", "level", "entity_id", "date"], bu=bu, source=platform, now=now), upsert=True))
    for i in range(0, len(ops), 2000):
        gd(schema.DB)["ad_metrics_daily"].bulk_write(ops[i:i + 2000], ordered=False)
    return len(ops)


def store_entities(gd: Callable, platform: str, collection: str, key: str, rows: Iterable[Dict[str, Any]], *, now: datetime) -> int:
    n = 0
    for r in rows:
        r = dict(r, platform=platform)
        bu = r.get("bu") if r.get("bu") in schema.BUS else None
        f, u = schema.upsert_ops(r, ["platform", key], bu=bu, source=platform, now=now)
        gd(schema.DB)[collection].update_one(f, u, upsert=True)
        n += 1
    return n


def pending_conversions(gd: Callable, platform: str, *, id_keys: List[str], since_days: int = 90,
                        now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Events not yet uploaded for leads that carry one of the platform's click IDs (or an email for hashed matching)."""
    from bson import ObjectId
    from marketing import touchpoints
    now = now or datetime.utcnow()
    ea, crm = gd(schema.DB), gd("crm_db")
    # only rows actually accepted by the platform count as done: shadow rows are re-offered once live, failures are retried
    done = {(u["lead_id"], u["event"]) for u in ea["offline_conversion_uploads"].find({"platform": platform, "status": "sent"},
                                                                                      {"lead_id": 1, "event": 1})}
    by_lead: Dict[str, Dict[str, Any]] = {}
    q = {"at": {"$gte": now - timedelta(days=since_days)}, "$or": [{f"click_ids.{k}": {"$exists": True}} for k in id_keys]}
    for t in ea["touchpoints"].find(q):
        cid = next(((k, t["click_ids"][k]) for k in id_keys if (t.get("click_ids") or {}).get(k)), None)
        if cid:
            by_lead.setdefault(t["lead_id"], {"click": cid, "click_at": t["at"]})
    out = []
    for lid, info in by_lead.items():
        lead = crm["leads"].find_one({"_id": ObjectId(lid)}) if ObjectId.is_valid(lid) else None
        if not lead:
            continue
        email = lead.get("email") or ""
        base = {"platform": platform, "lead_id": lid, "click_type": info["click"][0], "click_id": info["click"][1],
                "click_at": info["click_at"], "email_sha256": sha256_email(email), "phone_sha256": sha256_phone(lead.get("phone") or ""),
                "bu": lead.get("bu")}
        evs = [("lead", lead.get("created_at"), 0.0)]
        replied = ea["touchpoints"].find_one({"lead_id": lid, "kind": "mail_in"})
        biz_form = (lead.get("source") == "website_form" and email.rsplit("@", 1)[-1] not in FREE)
        if replied or biz_form:
            evs.append(("qualified_lead", (replied or {}).get("at") or lead.get("created_at"), 0.0))
        for c in touchpoints.conversions(gd, lead):
            evs.append((c["event"], c["at"], float(c.get("value_inr") or 0)))
        for ev, at, val in evs:
            if ev in EVENTS and isinstance(at, datetime) and (lid, ev) not in done and at >= info["click_at"] - timedelta(days=1):
                out.append({**base, "event": ev, "at": at, "value_inr": val})
    return out


def record_upload(gd: Callable, conv: Dict[str, Any], *, status: str, response: Any = None, now: Optional[datetime] = None) -> None:
    now = now or datetime.utcnow()
    doc = {k: conv.get(k) for k in ("platform", "lead_id", "event", "at", "value_inr", "click_type", "click_id")}
    doc.update(status=status, response=str(response)[:500] if response is not None else None)
    f, u = schema.upsert_ops(doc, ["platform", "lead_id", "event"], bu=conv.get("bu") if conv.get("bu") in schema.BUS else None,
                             source="offline_conversions", now=now)
    gd(schema.DB)["offline_conversion_uploads"].update_one(f, u, upsert=True)


def conversions_live(cfg: Dict[str, Any], platform: str) -> bool:
    return cfg.get("mode") == "live" and (cfg.get("action_modes") or {}).get(f"conversions:{platform}") == "live"


def attach_crm_outcomes(gd: Callable, platform: str, *, since: datetime, now: Optional[datetime] = None) -> int:
    """Leads / RFQs per campaign per day from the CRM (3.4.3), joined on the landing URL's utm_id (campaign ID,
    set by the tracking template: utm_id={campaignid}) or utm_campaign (= campaign name). Written onto the
    campaign rows of ad_metrics_daily so the rules and dashboard use CRM outcomes, not platform conversions."""
    from bson import ObjectId
    from marketing import touchpoints as tpm
    now = now or datetime.utcnow()
    ea = gd(schema.DB)
    camps = {c["campaign_id"]: c for c in ea["ad_campaigns"].find({"platform": platform})}
    by_name = {str(c.get("name") or "").strip().lower(): cid for cid, c in camps.items()}
    counts: Dict[tuple, Dict[str, float]] = {}
    seen = set()
    for t in ea["touchpoints"].find({"kind": {"$in": ["visit", "form"]}, "at": {"$gte": since}}):
        utm = t.get("utm") or {}
        cid = utm.get("utm_id") if utm.get("utm_id") in camps else by_name.get(str(utm.get("utm_campaign") or "").strip().lower())
        if not cid or (t["lead_id"], cid) in seen:
            continue
        seen.add((t["lead_id"], cid))
        day = t["at"].strftime("%Y-%m-%d")
        c = counts.setdefault((cid, day), {"leads": 0, "rfqs": 0, "won_inr": 0.0})
        c["leads"] += 1
        lead = gd("crm_db")["leads"].find_one({"_id": ObjectId(t["lead_id"])}) if ObjectId.is_valid(t["lead_id"]) else None
        for conv in (tpm.conversions(gd, lead) if lead else []):
            if conv["event"] == "rfq":
                c["rfqs"] += 1
            elif conv["event"] == "won":
                c["won_inr"] += float(conv.get("value_inr") or 0)
    for (cid, day), c in counts.items():
        ea["ad_metrics_daily"].update_one({"platform": platform, "level": "campaign", "entity_id": cid, "date": day},
                                          {"$set": {**c, "crm_joined_at": now}})
    return len(counts)
