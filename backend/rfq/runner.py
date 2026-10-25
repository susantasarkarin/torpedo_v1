"""Scheduled RFQ run (every 10 minutes): open mail RFQs without a decision ->
rfq.flow.process -> email_automation.rfq_decisions.

Shadow (default): decisions only. Live (owner switches config rfq.mode): the
result is also stamped on the opportunity (metadata.rfq.flow) and the
missing-info draft / priced lines go to the Review Queue. Nothing is mailed
here in either mode. Skips entirely until the extraction model has its own
endpoint (QWEN_ENDPOINT_<MODEL>), so the 7B task never lands on the 1.5B.
"""
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from bson import ObjectId

from rfq import flow

logger = logging.getLogger(__name__)


def _gd():
    from database import get_database
    return get_database


def model_hosted(qcfg: Dict[str, Any]) -> bool:
    model = qcfg["tasks"]["rfq_extraction"]["model"]
    return bool(os.getenv("QWEN_ENDPOINT_" + re.sub(r"[^A-Z0-9]+", "_", model.upper()).strip("_")))


def _text(md, opp) -> str:
    sid = ((opp.get("metadata") or {}).get("rfq") or {}).get("source_email_id")
    try:
        m = md.find_one({"_id": ObjectId(sid)}, {"subject": 1, "body_plain": 1}) if sid else None
    except Exception:
        m = None
    return ((m or {}).get("subject") or "") + "\n" + ((m or {}).get("body_plain") or "") if m else ""


def _bu(account_id: str, opp) -> Optional[str]:
    from crm360 import view
    try:
        return view.derive_bu(view.finance(account_id)["invoices"], [opp], view._mailbox_bu())["bu"]
    except Exception:
        return None


def _history(decisions, account_id: str) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {}
    for d in decisions.find({"account_id": account_id, "pricing": {"$exists": True}},
                            {"pricing": 1}).sort("decided_at", -1).limit(20):
        for p in d.get("pricing") or []:
            if p.get("client_cpi_usd") and len(out.setdefault(p["country"], [])) < 5:
                out[p["country"]].append(p["client_cpi_usd"])
    return out


def _go_live(gd, opp, d: Dict[str, Any]) -> None:
    from platform_core import review_queue
    from platform_core.audit import log_action
    ref = {"collection": "crm_db.opportunities", "id": d["opportunity_id"]}
    gd("crm_db")["opportunities"].update_one({"_id": opp["_id"]}, {"$set": {
        "metadata.rfq.flow": {k: d.get(k) for k in ("status", "line_items", "details", "missing", "pricing", "bu")},
        "metadata.rfq.flow_at": d["decided_at"]}})
    if d["status"] == "awaiting_info":
        review_queue.enqueue(type="rfq_missing_data", module="rfq", ref=ref, bu=d.get("bu"),
                             reason="critical fields missing: reply drafted, approve to send",
                             suggested={"reply_text": d["missing_info_draft"]}, payload={"missing": d["missing"]})
    elif d["status"] == "priced_review":
        reasons = sorted({r for p in d["pricing"] for r in p["review_reasons"]})
        review_queue.enqueue(type="unusual_price", module="rfq", ref=ref, bu=d.get("bu"),
                             reason="; ".join(reasons) or "extraction under review", payload={"pricing": d["pricing"]})
    log_action(actor="system", action="update", entity_type="opportunity", entity_id=d["opportunity_id"],
               reason=f"rfq flow: {d['status']}", source="rfq.runner")


def run_batch(now: Optional[datetime] = None, run=None, rows=None) -> Dict[str, Any]:
    from platform_core import config_store, ladder
    from pricing import rate_card
    gd = _gd()
    cfg, qcfg = config_store.get("rfq"), config_store.get("qwen")
    stats: Dict[str, Any] = {"mode": cfg["mode"], "decided": 0}
    if cfg["mode"] == "off":
        return stats
    if run is None:
        run = ladder.run          # rules (rfq.rules_extract) first in flow.process, then Qwen -> Haiku -> Sonnet
    now = now or datetime.utcnow()
    decisions = gd("email_automation")["rfq_decisions"]
    crm, md = gd("crm_db"), gd("torpedo_gmail")["email_metadata"]
    rules = list(crm["client_defaults"].find({})) + list(cfg.get("client_defaults_seed") or [])
    pricing_cfg = config_store.get("pricing")
    rows = rows if rows is not None else rate_card.load_rows(gd("cint_research"))
    q = {"status": "open", "metadata.rfq.source_email_id": {"$exists": True},
         "metadata.rfq.received_at": {"$gte": now - timedelta(days=int(cfg["lookback_days"]))}}
    for opp in crm["opportunities"].find(q).sort("metadata.rfq.received_at", -1).limit(int(cfg["batch"]) * 4):
        if stats["decided"] >= int(cfg["batch"]):
            break
        oid = str(opp["_id"])
        if decisions.count_documents({"opportunity_id": oid, "status": {"$ne": "deferred"}}, limit=1):
            continue
        text = _text(md, opp)
        if not text.strip():
            continue
        aid = str(opp.get("account_id") or "")
        try:
            account = crm["accounts"].find_one({"_id": ObjectId(aid)}) or {"_id": aid}
        except Exception:
            account = {"_id": aid}
        d = flow.process(opp, text, account=account, bu=_bu(aid, opp), rules=rules, rows=rows, cfg=cfg,
                         pricing_cfg=pricing_cfg, run=run, now=now,
                         client_markup=(account.get("pricing") or {}).get("markup"), history=_history(decisions, aid))
        d.update(mode=cfg["mode"], decided_at=now, flow_version=1)
        if d["status"] == "deferred":
            continue
        decisions.update_one({"opportunity_id": oid}, {"$set": d}, upsert=True)
        if cfg["mode"] == "live" and d["status"] not in ("extraction_failed",):
            _go_live(gd, opp, d)
        stats["decided"] += 1
        stats[d["status"]] = stats.get(d["status"], 0) + 1
    logger.info("rfq flow: %s", stats)
    return stats
