"""WhatsApp Business Platform, Cloud API (MARKETING_PLAN 3.5.3). Never cold.

Integrations > WhatsApp: access_token, webhook_verify_token; waba_id, phone_number_ids {"SFW": "<id>"}
(or {"ALL": "<id>"} for one shared number with BU routing by the template / conversation).
  reply()          free text inside the 24-hour service window (an inbox reply, approved in the Review Queue)
  send_template()  business-initiated: recorded opt-in + Meta-approved template + contact cap + kill switch +
                   live (action_modes["whatsapp:template"]); logged in marketing_touches
  templates        Claude drafts the 5 templates per BU (status draft) -> owner approves (owner_approved) ->
                   submit_templates() sends them for Meta review (PENDING) -> sync_templates() reads APPROVED / REJECTED
"""
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from marketing import credentials, inbox, schema

VERSION = os.getenv("META_GRAPH_VERSION", "v21.0")
GRAPH = f"https://graph.facebook.com/{VERSION}"

BRAND = {"SFW": "Survey Fieldwork", "COGENTIX": "Cogentix Research", "BIM": "BIM Wave Solutions"}
# (name, category, body with {{n}} placeholders, example values)
DRAFTS = [
    ("meeting_reminder", "UTILITY", "Hi {{1}}, a reminder of our call on {{2}} at {{3}} IST. Reply here if you need to move it. — {brand}",
     ["Asha", "Tue 28 Oct", "11:00"]),
    ("rfq_follow_up", "UTILITY", "Hi {{1}}, following up on your request for {{2}}. Could you confirm the target audience and timeline "
                                 "so we can share feasibility and cost? — {brand}", ["Asha", "a CATI study"]),
    ("quote_sent", "UTILITY", "Hi {{1}}, we've emailed our quote {{2}} for {{3}}. Happy to walk you through it. — {brand}",
     ["Asha", "Q-1042", "the brand health study"]),
    ("payment_reminder", "UTILITY", "Hi {{1}}, a reminder that invoice {{2}} for {{3}} was due on {{4}}. If it's already paid, "
                                    "please ignore this. — {brand}", ["Asha", "SF/25-26/104", "INR 1,20,000", "20 Oct"]),
    ("re_engagement", "MARKETING", "Hi {{1}}, it's been a while since we worked on {{2}}. Is there anything coming up we could help "
                                   "with? Reply STOP to opt out. — {brand}", ["Asha", "your last study"]),
]


class NotConfigured(RuntimeError):
    pass


def _cred(gd=None):
    c = credentials.secrets("whatsapp", gd)
    if not c.get("access_token"):
        raise NotConfigured("WhatsApp: access token needed (Integrations)")
    return c


def _phone_id(settings: Dict[str, Any], bu: Optional[str]) -> str:
    ids = settings.get("phone_number_ids") or {}
    pid = ids.get(bu) or ids.get("ALL")
    if not pid:
        raise RuntimeError(f"no WhatsApp number for {bu}")
    return str(pid)


def _post(path: str, token: str, body: Dict[str, Any], http=None) -> Dict[str, Any]:
    http = http or __import__("requests")
    r = http.post(f"{GRAPH}/{path}", json=body, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    d = r.json() if hasattr(r, "json") else {}
    if r.status_code >= 400 or d.get("error"):
        raise RuntimeError(f"WhatsApp HTTP {r.status_code}: {str((d.get('error') or {}).get('message') or d)[:200]}")
    return d


def _to(phone: str) -> str:
    import re
    d = re.sub(r"\D", "", phone or "")
    return "91" + d if len(d) == 10 else d


def reply(item: Dict[str, Any], text: str, *, gd=None, http=None) -> Dict[str, Any]:
    """Inbox sender for channel whatsapp: free text, only inside the 24-hour window (checked again here)."""
    c = _cred(gd)
    phone = (item.get("author") or {}).get("phone") or item.get("thread_id")
    ok, why = inbox.whatsapp_can_send(gd or _gd(), phone)
    if not ok or why != "inside the 24-hour service window":
        raise RuntimeError(f"cannot send free text: {why}")
    res = _post(f"{_phone_id(c.get('settings') or {}, item.get('bu'))}/messages", c["access_token"],
                {"messaging_product": "whatsapp", "to": _to(phone), "type": "text", "text": {"body": text[:4096]}}, http)
    return {"id": ((res.get("messages") or [{}])[0]).get("id")}


def _gd():
    from database import get_database
    return get_database


def send_template(gd: Optional[Callable], *, phone: str, template: str, bu: str, params: List[str], lead_id: Optional[str] = None,
                  language: str = "en", cfg: Optional[Dict[str, Any]] = None, http=None, now: Optional[datetime] = None) -> Dict[str, Any]:
    gd = gd or _gd()
    now = now or datetime.utcnow()
    if cfg is None:
        from platform_core import config_store
        cfg = config_store.get("marketing")
    from marketing import config as mcfg
    if mcfg.killed(cfg, bu):
        return {"sent": False, "why": "kill switch on"}
    ok, why = inbox.whatsapp_can_send(gd, phone, template=template, bu=bu, now=now)
    if not ok:
        return {"sent": False, "why": why}
    cap_ok, cap_why = inbox.contact_cap_ok(gd, lead_id=lead_id, phone=phone, now=now, cfg=cfg)
    if not cap_ok:
        return {"sent": False, "why": cap_why}
    live = cfg.get("mode") == "live" and (cfg.get("action_modes") or {}).get("whatsapp:template") == "live"
    touch = {"channel": "whatsapp", "automated": True, "lead_id": lead_id, "phone_hash": inbox.phone_hash(phone), "template": template,
             "at": now, "live": live}
    if not live:
        gd(schema.DB)["marketing_touches"].insert_one(schema.stamp({**touch, "status": "shadow"}, bu=bu, source="whatsapp", now=now))
        return {"sent": False, "why": "shadow", "would_send": template}
    c = _cred(gd)
    body = {"messaging_product": "whatsapp", "to": _to(phone), "type": "template",
            "template": {"name": f"{bu.lower()}_{template}", "language": {"code": language},
                         "components": [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params]}]}}
    res = _post(f"{_phone_id(c.get('settings') or {}, bu)}/messages", c["access_token"], body, http)
    gd(schema.DB)["marketing_touches"].insert_one(schema.stamp({**touch, "status": "sent",
                                                                "message_id": ((res.get("messages") or [{}])[0]).get("id")},
                                                               bu=bu, source="whatsapp", now=now))
    return {"sent": True}


def seed_templates(gd: Optional[Callable] = None, now: Optional[datetime] = None) -> int:
    gd = gd or _gd()
    now = now or datetime.utcnow()
    col, n = gd(schema.DB)["whatsapp_templates"], 0
    for bu, brand in BRAND.items():
        for name, cat, body, ex in DRAFTS:
            if col.find_one({"bu": bu, "name": name, "language": "en"}):
                continue
            col.insert_one(schema.stamp({"name": name, "meta_name": f"{bu.lower()}_{name}", "language": "en", "category": cat,
                                         "body": body.replace("{brand}", brand), "example": ex, "status": "draft",
                                         "drafted_by": "claude"}, bu=bu, source="whatsapp_template_draft", now=now))
            n += 1
    return n


def submit_templates(gd: Optional[Callable] = None, *, http=None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Only templates the owner approved (status owner_approved) go to Meta for review."""
    gd = gd or _gd()
    now = now or datetime.utcnow()
    col = gd(schema.DB)["whatsapp_templates"]
    todo = list(col.find({"status": "owner_approved"}))
    if not todo:
        return {"submitted": 0}
    try:
        c = _cred(gd)
    except NotConfigured as e:
        return {"skipped": str(e), "waiting": len(todo)}
    waba = (c.get("settings") or {}).get("waba_id")
    if not waba:
        return {"skipped": "no waba_id", "waiting": len(todo)}
    rep = {"submitted": 0, "errors": []}
    for t in todo:
        body = {"name": t["meta_name"], "language": t["language"], "category": t["category"],
                "components": [{"type": "BODY", "text": t["body"], "example": {"body_text": [t["example"]]}}]}
        try:
            res = _post(f"{waba}/message_templates", c["access_token"], body, http)
            col.update_one({"_id": t["_id"]}, {"$set": {"status": "pending", "meta_id": res.get("id"), "submitted_at": now, "updated_at": now}})
            rep["submitted"] += 1
        except Exception as e:
            rep["errors"].append(f"{t['meta_name']}: {str(e)[:150]}")
    return rep


def sync_templates(gd: Optional[Callable] = None, *, http=None, now: Optional[datetime] = None) -> Dict[str, Any]:
    gd = gd or _gd()
    now = now or datetime.utcnow()
    try:
        c = _cred(gd)
    except NotConfigured as e:
        return {"skipped": str(e)}
    waba = (c.get("settings") or {}).get("waba_id")
    if not waba:
        return {"skipped": "no waba_id"}
    http = http or __import__("requests")
    r = http.get(f"{GRAPH}/{waba}/message_templates", params={"fields": "name,status,language,rejected_reason", "limit": 200},
                 headers={"Authorization": f"Bearer {c['access_token']}"}, timeout=30)
    col, n = gd(schema.DB)["whatsapp_templates"], 0
    for t in (r.json() or {}).get("data") or []:
        st = (t.get("status") or "").lower()            # approved / rejected / pending / paused / disabled
        res = col.update_one({"meta_name": t.get("name"), "language": t.get("language")},
                             {"$set": {"status": st, "rejected_reason": t.get("rejected_reason"), "synced_at": now, "updated_at": now}})
        n += 1
    return {"synced": n}


def register() -> None:
    inbox.register_sender("whatsapp", lambda item, text: reply(item, text))
