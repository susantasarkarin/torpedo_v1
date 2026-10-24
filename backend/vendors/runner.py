"""Vendor bid run (every 15 minutes): follow-ups / no_bid by working hours,
and parsing of vendor replies the mail pipeline linked to a bid ([VB-...]).

Shadow (default): decisions only, in email_automation.vendor_decisions.
Live (owner, config vendors.mode): bid records are updated; the follow-up is a
Review Queue draft until the vendor templates are approved (Checkpoint 3).
Bid values only ever go on the vendor bid record, never on the client RFQ.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from bson import ObjectId

from vendors import bids

logger = logging.getLogger(__name__)
IST = timedelta(hours=5, minutes=30)


def _gd():
    from database import get_database
    return get_database


def run(now: Optional[datetime] = None, run_model=None) -> Dict[str, Any]:
    from platform_core import config_store, review_queue
    gd = _gd()
    cfg = config_store.get("vendors")
    now = now or datetime.utcnow()
    live = cfg["mode"] == "live"
    col = gd("crm_db")["vendor_bids"]
    out = gd("email_automation")["vendor_decisions"]
    stats: Dict[str, Any] = {"mode": cfg["mode"], "follow_up": 0, "no_bid": 0, "parsed": 0}

    for b in col.find({"status": "requested"}):
        act = bids.bid_due_action(b, now + IST, cfg)
        if not act:
            continue
        stats[act] += 1
        out.insert_one({"kind": act, "bid_id": str(b["_id"]), "ref_id": b.get("ref_id"), "mode": cfg["mode"], "at": now})
        if live and act == "no_bid":
            col.update_one({"_id": b["_id"]}, {"$set": {"status": "no_bid", "no_bid_at": now}})
        elif live:
            col.update_one({"_id": b["_id"]}, {"$set": {"followed_up_at": now}})
            review_queue.enqueue(type="vendor_bid", module="vendors", ref={"collection": "crm_db.vendor_bids", "id": str(b["_id"])},
                                 reason="no reply after 4 working hours: follow-up drafted",
                                 suggested={"subject": f"Re: [{b.get('ref_id')}] Bid request", "body": "Following up on our bid request below."})

    if run_model is None:
        from platform_core import qwen_gateway
        run_model = qwen_gateway.run
    md = gd("torpedo_gmail")["email_metadata"]
    for dec in gd("email_automation")["mail_decisions"].find({"link.type": "vendor_bid", "vendor_parsed": {"$ne": True}}).limit(10):
        bid_id = (dec.get("link") or {}).get("vendor_bid_id")
        try:
            msg = md.find_one({"_id": ObjectId(dec["message_id"])}, {"subject": 1, "body_plain": 1})
        except Exception:
            msg = None
        if not bid_id or not msg:
            continue
        r = run_model(task="vendor_bid_parse", system=bids.BID_SYSTEM, subject=msg.get("subject") or "",
                      body=msg.get("body_plain") or "", schema=bids.BID_SCHEMA, code_check=bids.bid_code_check,
                      ref={"collection": "crm_db.vendor_bids", "id": bid_id})
        if r.get("status") in ("deferred", "failed"):
            continue
        data = r.get("data") or {}
        out.insert_one({"kind": "parsed", "bid_id": bid_id, "message_id": dec["message_id"], "data": data,
                        "problems": r.get("problems") or [], "status": r.get("status"), "mode": cfg["mode"], "at": now})
        gd("email_automation")["mail_decisions"].update_one({"_id": dec["_id"]}, {"$set": {"vendor_parsed": True}})
        if live:
            upd = {"status": "declined" if data.get("declined") else "received", "parsed_at": now,
                   "review_item": r.get("review_item"), "parse_status": r.get("status"),
                   **{k: data.get(k) for k in ("cpi", "currency", "feasible_n", "timeline_days", "conditions")}}
            col.update_one({"_id": ObjectId(bid_id)}, {"$set": upd})
        stats["parsed"] += 1
    logger.info("vendor run: %s", stats)
    return stats
