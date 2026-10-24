"""Shadow-run report (CRM plan Phase 5): what each module WOULD have done.

One row per module from its decisions collection over the window, with
counts by outcome and a few masked samples, so the owner can review 5
shadow days before switching a module live. Nothing here sends or changes.
"""
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

SOURCES = [
    # module, collection in email_automation, time field, outcome field, config section that holds .mode
    ("mail_pipeline", "mail_decisions", "decided_at", "category.category", None),
    ("rfq", "rfq_decisions", "decided_at", "status", "rfq"),
    ("ops", "ops_decisions", "decided_at", None, "ops"),
    ("vendors", "vendor_decisions", "at", "kind", "vendors"),
    ("reengagement", "reengagement_decisions", "at", "kind", "reengagement"),
    ("service_delivery", "service_delivery_decisions", "at", None, "service_delivery"),
    ("web", "web_decisions", "at", "action", "web"),
    ("finance", "finance_decisions", "at", "kind", "accounting"),
    ("outbox_preview (sandboxed mail)", "outbox_preview", "created_at", "channel", None),
]
_EMAIL = re.compile(r"([\w.+-]{1,2})[\w.+-]*@([\w-]+\.[\w.-]+)")


def _mask(v):
    if isinstance(v, str):
        return _EMAIL.sub(r"\1***@\2", v)[:160]
    if isinstance(v, dict):
        return {k: _mask(x) for k, x in list(v.items())[:12] if k not in ("_id", "body", "raw_output", "clean_input")}
    if isinstance(v, list):
        return [_mask(x) for x in v[:5]]
    return v


def _get(d, dotted):
    for p in dotted.split("."):
        d = d.get(p) if isinstance(d, dict) else None
    return d


def build(gd, hours: int = 24, now: Optional[datetime] = None) -> Dict[str, Any]:
    from platform_core import config_store
    now = now or datetime.utcnow()
    since = now - timedelta(hours=hours)
    ea = gd("email_automation")
    rows = []
    for module, col, tf, of, section in SOURCES:
        docs = list(ea[col].find({tf: {"$gte": since}}).sort(tf, -1).limit(2000))
        outcomes = Counter(str(_get(d, of)) for d in docs) if of else Counter()
        mode = None
        if section:
            try:
                mode = config_store.get(section).get("mode")
            except Exception:
                mode = "?"
        rows.append({"module": module, "mode": mode or ("sandbox/shadow" if col != "mail_decisions" else "shadow"),
                     "decisions": len(docs), "outcomes": dict(outcomes.most_common(10)),
                     "samples": [_mask(d) for d in docs[:3]]})
    return {"window_hours": hours, "generated_at": now, "modules": rows}
