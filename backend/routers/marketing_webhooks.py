"""Inbound webhooks -> unified inbox (MARKETING_PLAN 3.5.2, 3.5.3, 3.7).

  /api/webhooks/meta      Facebook page feed comments, Messenger, Instagram comments + DMs, Lead Ads
  /api/webhooks/whatsapp  WhatsApp Cloud API messages

Public (AuthGuard: ^/webhooks?/), but every POST must carry a valid
X-Hub-Signature-256 = HMAC-SHA256(app secret, raw body); the GET handshake must
present the verify token. Both come from Integrations (encrypted). Without them
the endpoints refuse. The page / Instagram account / phone-number ID decides
the BU (Integrations settings page_ids, instagram_ids, phone_number_ids as
{"SFW": "<id>", ...}). Lead Ads arrive as an ID only: stored pending, fetched
with the page token by the Meta integration job.
"""
import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

from marketing import credentials, inbox, schema

router = APIRouter(prefix="/api/webhooks", tags=["Marketing webhooks"])


def _gd(name):
    from database import get_database
    return get_database(name)


def _creds(platform: str) -> Dict[str, Any]:
    try:
        return credentials.secrets(platform)
    except Exception:
        return {"settings": {}}


def _bu_for(settings: Dict[str, Any], key: str, ident: Optional[str]) -> Optional[str]:
    for bu, v in (settings.get(key) or {}).items():
        if ident and (ident == v or (isinstance(v, list) and ident in v)):
            return bu
    return None


def verify_signature(raw: bytes, header: Optional[str], secret: Optional[str]) -> bool:
    if not secret or not header or not header.startswith("sha256="):
        return False
    want = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header.split("=", 1)[1])


def _handshake(request: Request, token: Optional[str]):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and token and hmac.compare_digest(q.get("hub.verify_token", ""), token):
        return PlainTextResponse(q.get("hub.challenge", ""))
    return Response(status_code=403)


def _ts(v) -> datetime:
    try:
        return datetime.utcfromtimestamp(int(v)) if v is not None else datetime.utcnow()
    except (TypeError, ValueError):
        return datetime.utcnow()


def parse_meta(body: Dict[str, Any], settings: Dict[str, Any]):
    """-> list of ingest kwargs + list of pending lead ids."""
    out, leads = [], []
    obj = body.get("object")
    for e in body.get("entry") or []:
        eid = str(e.get("id") or "")
        bu = _bu_for(settings, "instagram_ids" if obj == "instagram" else "page_ids", eid)
        for ch in e.get("changes") or []:
            f, v = ch.get("field"), ch.get("value") or {}
            if obj == "page" and f == "feed" and v.get("item") == "comment" and v.get("verb") == "add":
                fr = v.get("from") or {}
                if fr.get("id") == eid:
                    continue                                            # our own page's comment
                out.append(dict(channel="facebook_comment", external_id=str(v.get("comment_id")), bu=bu, text=v.get("message") or "",
                                at=_ts(v.get("created_time")), author={"name": fr.get("name"), "handle": fr.get("id")},
                                kind="comment", thread_id=str(v.get("post_id") or "")))
            elif obj == "page" and f == "leadgen":
                leads.append({"leadgen_id": str(v.get("leadgen_id")), "form_id": v.get("form_id"), "page_id": eid, "bu": bu,
                              "ad_id": v.get("ad_id"), "created_time": v.get("created_time")})
            elif obj == "instagram" and f == "comments":
                fr = v.get("from") or {}
                out.append(dict(channel="instagram_comment", external_id=str(v.get("id")), bu=bu, text=v.get("text") or "",
                                author={"name": fr.get("username"), "handle": fr.get("id")}, kind="comment",
                                thread_id=str((v.get("media") or {}).get("id") or "")))
        for m in e.get("messaging") or []:
            msg, snd = m.get("message") or {}, (m.get("sender") or {}).get("id")
            if not msg or msg.get("is_echo") or snd == eid:
                continue
            out.append(dict(channel="instagram_dm" if obj == "instagram" else "messenger", external_id=str(msg.get("mid")), bu=bu,
                            text=msg.get("text") or "[attachment]", at=_ts((m.get("timestamp") or 0) // 1000 or None),
                            author={"handle": snd}, kind="dm", thread_id=snd))
    return out, leads


def parse_whatsapp(body: Dict[str, Any], settings: Dict[str, Any]):
    out = []
    for e in body.get("entry") or []:
        for ch in e.get("changes") or []:
            v = ch.get("value") or {}
            bu = _bu_for(settings, "phone_number_ids", str((v.get("metadata") or {}).get("phone_number_id") or ""))
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in v.get("contacts") or []}
            for m in v.get("messages") or []:
                text = (m.get("text") or {}).get("body") or (m.get("button") or {}).get("text") or f"[{m.get('type')}]"
                out.append(dict(channel="whatsapp", external_id=str(m.get("id")), bu=bu, text=text, at=_ts(m.get("timestamp")),
                                author={"name": names.get(m.get("from")), "phone": m.get("from")}, kind="message",
                                thread_id=m.get("from")))
    return out


@router.get("/meta")
async def meta_verify(request: Request):
    return _handshake(request, _creds("meta").get("webhook_verify_token"))


@router.post("/meta")
async def meta_receive(request: Request):
    raw = await request.body()
    c = _creds("meta")
    if not verify_signature(raw, request.headers.get("x-hub-signature-256"), c.get("app_secret")):
        return Response(status_code=403)
    items, leads = parse_meta(json.loads(raw or b"{}"), c.get("settings") or {})
    for kw in items:
        try:
            inbox.ingest(_gd, **kw)
        except Exception:
            pass
    ea = _gd(schema.DB)
    for l in leads:
        ea["lead_form_pending"].update_one({"leadgen_id": l["leadgen_id"]}, {"$setOnInsert": {**l, "status": "pending",
                                                                                             "received_at": datetime.utcnow()}}, upsert=True)
    return {"ok": True, "items": len(items), "leads": len(leads)}


@router.get("/whatsapp")
async def wa_verify(request: Request):
    return _handshake(request, _creds("whatsapp").get("webhook_verify_token"))


@router.post("/whatsapp")
async def wa_receive(request: Request):
    raw = await request.body()
    secret = _creds("meta").get("app_secret")                    # the WhatsApp app is the Meta app
    if not verify_signature(raw, request.headers.get("x-hub-signature-256"), secret):
        return Response(status_code=403)
    items = parse_whatsapp(json.loads(raw or b"{}"), _creds("whatsapp").get("settings") or {})
    for kw in items:
        try:
            inbox.ingest(_gd, **kw)
        except Exception:
            pass
    return {"ok": True, "items": len(items)}
