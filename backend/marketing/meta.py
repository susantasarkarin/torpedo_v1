"""Meta: Facebook + Instagram (MARKETING_PLAN 3.4, 3.5.2) via the Graph / Marketing API.

Integrations > Meta: system_user_token, app_secret, webhook_verify_token (secrets); app_id, page_ids,
instagram_ids, ad_account_ids, pixel_ids (settings, per BU as {"SFW": "<id>"}).
  import_daily        ad insights per day at campaign / ad set / ad level (spend in INR), campaigns, ads
                      (effective_status DISAPPROVED), account status (billing / disabled)
  upload_conversions  Conversions API (lead / QualifiedLead / RFQ / Purchase with won INR), fbclid as fbc +
                      hashed email / phone; never sent twice; shadow until live
  fetch_lead_ads      Lead Ads ids from the webhook -> field data -> CRM lead + inbox item (1 h SLA)
  publishers          Facebook page post, Instagram image post (content calendar, approved items only)
  senders             replies to FB / IG comments, Messenger and Instagram DMs (approved in the Review Queue)
  executors           pause / resume campaign, daily budget shift, with undo
Version: META_GRAPH_VERSION.
"""
import json
import os
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from marketing import ads_common, credentials, schema

VERSION = os.getenv("META_GRAPH_VERSION", "v21.0")
GRAPH = f"https://graph.facebook.com/{VERSION}"
EVENT_NAMES = {"lead": "Lead", "qualified_lead": "QualifiedLead", "rfq": "RFQ", "won": "Purchase"}
BILLING_BAD = {2: "DISABLED", 3: "UNSETTLED", 7: "PENDING_RISK_REVIEW", 8: "PENDING_SETTLEMENT", 9: "IN_GRACE_PERIOD", 101: "CLOSED"}
LEAD_ACTIONS = ("lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead", "leadgen_grouped")


class NotConfigured(RuntimeError):
    pass


def _requests():
    import requests
    return requests


class Client:
    def __init__(self, cred: Dict[str, Any], http=None):
        if not cred.get("system_user_token"):
            raise NotConfigured("Meta: system user token needed (Integrations)")
        self.token, self.s, self.http = cred["system_user_token"], cred.get("settings") or {}, http or _requests()
        self._page_tokens: Dict[str, str] = {}

    def get(self, path: str, token: Optional[str] = None, **params) -> Dict[str, Any]:
        r = self.http.get(f"{GRAPH}/{path.lstrip('/')}", params={**params, "access_token": token or self.token}, timeout=60)
        return _ok(r)

    def post(self, path: str, token: Optional[str] = None, **data) -> Dict[str, Any]:
        r = self.http.post(f"{GRAPH}/{path.lstrip('/')}", data={**data, "access_token": token or self.token}, timeout=60)
        return _ok(r)

    def paged(self, path: str, **params) -> List[Dict[str, Any]]:
        out, d = [], self.get(path, **params)
        while True:
            out += d.get("data") or []
            nxt = (d.get("paging") or {}).get("next")
            if not nxt:
                return out
            d = _ok(self.http.get(nxt, timeout=60))

    def page_token(self, page_id: str) -> str:
        if page_id not in self._page_tokens:
            self._page_tokens[page_id] = self.get(page_id, fields="access_token")["access_token"]
        return self._page_tokens[page_id]


def _ok(r):
    try:
        d = r.json()
    except Exception:
        d = {}
    if getattr(r, "status_code", 200) >= 400 or (isinstance(d, dict) and d.get("error")):
        e = (d or {}).get("error") or {}
        raise RuntimeError(f"Meta HTTP {getattr(r, 'status_code', '?')}: {str(e.get('message') or getattr(r, 'text', ''))[:250]}")
    return d


def client(gd=None, http=None) -> Client:
    return Client(credentials.secrets("meta", gd), http)


def per_bu(setting) -> List[tuple]:
    out = []
    for bu, v in (setting or {}).items():
        for x in (v if isinstance(v, list) else [v]):
            if x:
                out.append((bu, str(x)))
    return out


def _act(aid: str) -> str:
    return aid if aid.startswith("act_") else f"act_{aid}"


def import_daily(gd: Optional[Callable] = None, *, days: int = 3, today_only: bool = False, now: Optional[datetime] = None,
                 cl: Optional[Client] = None) -> Dict[str, Any]:
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    try:
        cl = cl or client(gd)
    except NotConfigured as e:
        return {"skipped": str(e)}
    ist_today = (now + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    since, until = ((ist_today, ist_today) if today_only else
                    ((now - timedelta(days=days)).strftime("%Y-%m-%d"), (now - timedelta(days=1)).strftime("%Y-%m-%d")))
    rates = ads_common.fx(gd)
    rep: Dict[str, Any] = {"window": [since, until], "accounts": {}, "errors": []}
    for bu, aid in per_bu(cl.s.get("ad_account_ids")):
        act = _act(aid)
        try:
            acc = cl.get(act, fields="name,currency,account_status,disable_reason")
            ccy = acc.get("currency") or "INR"
            st = int(acc.get("account_status") or 1)
            ads_common.store_entities(gd, "meta", "ad_accounts", "account_id", [{
                "account_id": act, "name": acc.get("name"), "currency": ccy, "bu": bu, "status": BILLING_BAD.get(st, "ACTIVE"),
                "billing_problem": st in (3, 8, 9)}], now=now)
            camps = cl.paged(f"{act}/campaigns", fields="id,name,status,effective_status,daily_budget,lifetime_budget", limit=500)
            ads_common.store_entities(gd, "meta", "ad_campaigns", "campaign_id", [{
                "campaign_id": c["id"], "name": c.get("name"), "status": c.get("effective_status") or c.get("status"), "bu": bu,
                "account_id": act, "daily_budget_minor": int(c["daily_budget"]) if c.get("daily_budget") else None,
                "learning_phase": False} for c in camps], now=now)
            ads = cl.paged(f"{act}/ads", fields="id,name,adset_id,campaign_id,effective_status", limit=500)
            ads_common.store_entities(gd, "meta", "ads", "ad_id", [{
                "ad_id": a["id"], "name": a.get("name"), "group_id": a.get("adset_id"), "campaign_id": a.get("campaign_id"), "bu": bu,
                "status": a.get("effective_status"), "review_status": "DISAPPROVED" if a.get("effective_status") == "DISAPPROVED" else None}
                for a in ads], now=now)
            rows = []
            for level, idf in (("campaign", "campaign_id"), ("adset", "adset_id"), ("ad", "ad_id")):
                for r in cl.paged(f"{act}/insights", level=level, time_increment=1, limit=500,
                                  time_range=json.dumps({"since": since, "until": until}),
                                  fields="campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend,impressions,clicks,reach,frequency,actions"):
                    leads = sum(float(a.get("value") or 0) for a in r.get("actions") or [] if a.get("action_type") in LEAD_ACTIONS)
                    rows.append({"level": {"adset": "ad_group"}.get(level, level), "entity_id": r.get(idf), "date": r.get("date_start"),
                                 "campaign_id": r.get("campaign_id"), "group_id": r.get("adset_id"), "bu": bu,
                                 "name": r.get(f"{level}_name") or r.get("campaign_name"),
                                 "spend_inr": ads_common.to_inr(float(r.get("spend") or 0), ccy, rates),
                                 "impressions": float(r.get("impressions") or 0), "clicks": float(r.get("clicks") or 0),
                                 "reach": float(r.get("reach") or 0), "frequency": float(r.get("frequency") or 0),
                                 "conversions": leads, "platform_leads": leads})
            n = ads_common.store_metrics(gd, "meta", rows, now=now)
            rep["accounts"][act] = {"bu": bu, "rows": n, "campaigns": len(camps), "ads": len(ads), "status": BILLING_BAD.get(st, "ACTIVE")}
        except Exception as e:
            rep["errors"].append(f"{act}: {str(e)[:200]}")
    rep["crm_joined"] = ads_common.attach_crm_outcomes(gd, "meta", since=now - timedelta(days=max(days, 30)), now=now)
    credentials.mark("meta", ok=not rep["errors"], error="; ".join(rep["errors"])[:300] or None, gd=gd)
    return rep


def upload_conversions(gd: Optional[Callable] = None, *, cfg: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None,
                       cl: Optional[Client] = None) -> Dict[str, Any]:
    if gd is None:
        from database import get_database as gd
    if cfg is None:
        from platform_core import config_store
        cfg = config_store.get("marketing")
    now = now or datetime.utcnow()
    pend = ads_common.pending_conversions(gd, "meta", id_keys=["fbclid"], now=now)
    rep = {"pending": len(pend), "sent": 0, "shadow": 0, "errors": []}
    if not pend:
        return rep
    if not ads_common.conversions_live(cfg, "meta"):
        for p in pend:
            ads_common.record_upload(gd, p, status="shadow", now=now)
        rep["shadow"] = len(pend)
        return rep
    try:
        cl = cl or client(gd)
    except NotConfigured as e:
        return {**rep, "skipped": str(e)}
    pixels = dict(per_bu(cl.s.get("pixel_ids")))
    for p in pend:
        pixel = pixels.get(p.get("bu"))
        if not pixel:
            ads_common.record_upload(gd, p, status="failed", response="no pixel / dataset for this BU", now=now)
            rep["errors"].append(f"{p['lead_id']}: no pixel for {p.get('bu')}")
            continue
        ud = {"fbc": f"fb.1.{int(p['click_at'].timestamp() * 1000)}.{p['click_id']}"}
        if p.get("email_sha256"):
            ud["em"] = [p["email_sha256"]]
        if p.get("phone_sha256"):
            ud["ph"] = [p["phone_sha256"]]
        ev = {"event_name": EVENT_NAMES[p["event"]], "event_time": int(p["at"].timestamp()), "action_source": "system_generated",
              "event_id": f"{p['lead_id']}:{p['event']}", "user_data": ud}
        if p["event"] == "won":
            ev["custom_data"] = {"value": p["value_inr"] or 0, "currency": "INR"}
        try:
            res = cl.post(f"{pixel}/events", data=json.dumps([ev]))
            ads_common.record_upload(gd, p, status="sent", response=res, now=now)
            rep["sent"] += 1
        except Exception as e:
            ads_common.record_upload(gd, p, status="failed", response=str(e), now=now)
            rep["errors"].append(str(e)[:120])
    return rep


def fetch_lead_ads(gd: Optional[Callable] = None, *, now: Optional[datetime] = None, cl: Optional[Client] = None) -> Dict[str, Any]:
    """Pending Lead Ads ids (from the webhook) -> form answers -> CRM lead (dedupe by email) + inbox item."""
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    ea = gd(schema.DB)
    pend = list(ea["lead_form_pending"].find({"status": "pending"}).limit(100))
    if not pend:
        return {"fetched": 0}
    try:
        cl = cl or client(gd)
    except NotConfigured as e:
        return {"skipped": str(e), "pending": len(pend)}
    from marketing import inbox
    rep = {"fetched": 0, "errors": []}
    for p in pend:
        try:
            tok = cl.page_token(p["page_id"]) if p.get("page_id") else None
            d = cl.get(p["leadgen_id"], token=tok, fields="created_time,field_data,ad_id,form_id,campaign_id")
            f = {x.get("name"): (x.get("values") or [""])[0] for x in d.get("field_data") or []}
            email = (f.get("email") or "").strip().lower()
            name = f.get("full_name") or " ".join(x for x in (f.get("first_name"), f.get("last_name")) if x)
            crm = gd("crm_db")["leads"]
            lead = crm.find_one({"email": email}) if email else None
            if lead:
                lid = lead["_id"]
                crm.update_one({"_id": lid}, {"$set": {"last_inbound_at": now, "updated_at": now}, "$addToSet": {"bus": p.get("bu")}})
            else:
                lid = crm.insert_one({"email": email or None, "name": name or None, "phone": f.get("phone_number"),
                                      "company": f.get("company_name"), "source": "facebook_lead_ad", "bu": p.get("bu"),
                                      "bus": [p.get("bu")], "status": "new", "intent": "positive_inbound", "created_at": now,
                                      "updated_at": now, "metadata": {"source": "facebook_lead_ad", "form_id": d.get("form_id"),
                                                                       "ad_id": d.get("ad_id"), "campaign_id": d.get("campaign_id")}}).inserted_id
            text = "; ".join(f"{k}: {v}" for k, v in f.items() if k not in ("email", "phone_number", "full_name"))
            inbox.ingest(gd, channel="facebook_lead_ad", external_id=p["leadgen_id"], bu=p.get("bu"), text=text or "Lead form submitted",
                         author={"name": name, "email": email, "phone": f.get("phone_number")}, kind="lead_form", sender_type="client")
            ea["touchpoints"].update_one({"tp_key": f"{lid}:lead_form:{p['leadgen_id']}"}, {"$set": schema.stamp({
                "tp_key": f"{lid}:lead_form:{p['leadgen_id']}", "lead_id": str(lid), "kind": "lead_form", "channel": "paid_social",
                "at": now, "utm": {"utm_source": "facebook", "utm_medium": "paid_social", "utm_id": d.get("campaign_id")}},
                bu=p.get("bu") if p.get("bu") in schema.BUS else None, source="meta_lead_ads", now=now)}, upsert=True)
            ea["lead_form_pending"].update_one({"_id": p["_id"]}, {"$set": {"status": "fetched", "lead_id": str(lid), "fetched_at": now}})
            rep["fetched"] += 1
        except Exception as e:
            rep["errors"].append(f"{p['leadgen_id']}: {str(e)[:150]}")
    return rep


# ------------------------------------------------------------------ publishers (content) + senders (inbox)
def _page_for(cl: Client, bu: str, key: str = "page_ids") -> str:
    pid = dict(per_bu(cl.s.get(key))).get(bu)
    if not pid:
        raise RuntimeError(f"no {key[:-4]} id for {bu}")
    return pid


def publish_facebook(item: Dict[str, Any]) -> Dict[str, Any]:
    cl = client()
    pid = _page_for(cl, item["bu"])
    data = {"message": item.get("body") or ""}
    if item.get("link"):
        data["link"] = item["link"]
    res = cl.post(f"{pid}/feed", token=cl.page_token(pid), **data)
    return {"post_id": res.get("id"), "url": f"https://www.facebook.com/{res.get('id')}"}


def publish_instagram(item: Dict[str, Any]) -> Dict[str, Any]:
    if not item.get("image_url"):
        raise RuntimeError("Instagram posts need an image_url on the content item")
    cl = client()
    ig = _page_for(cl, item["bu"], "instagram_ids")
    pid = _page_for(cl, item["bu"])
    tok = cl.page_token(pid)
    cap = (item.get("body") or "") + ("\n\n" + " ".join(item.get("hashtags") or []) if item.get("hashtags") else "")
    media = cl.post(f"{ig}/media", token=tok, image_url=item["image_url"], caption=cap)
    res = cl.post(f"{ig}/media_publish", token=tok, creation_id=media["id"])
    return {"post_id": res.get("id"), "url": None}


def _reply(item: Dict[str, Any], text: str) -> Dict[str, Any]:
    cl = client()
    pid = _page_for(cl, item.get("bu"))
    tok = cl.page_token(pid)
    ch = item["channel"]
    if ch == "facebook_comment":
        return cl.post(f"{item['external_id']}/comments", token=tok, message=text)
    if ch == "instagram_comment":
        return cl.post(f"{item['external_id']}/replies", token=tok, message=text)
    if ch in ("messenger", "instagram_dm"):
        if datetime.utcnow() - item["at"] > timedelta(hours=24):
            raise RuntimeError("outside Meta's 24-hour messaging window: reply on the platform")
        return cl.post(f"{pid}/messages", token=tok, recipient=json.dumps({"id": item.get("thread_id")}), messaging_type="RESPONSE",
                       message=json.dumps({"text": text}))
    raise RuntimeError(f"no Meta sender for {ch}")


# ------------------------------------------------------------------ executors (3.4.6)
def _status(status):
    def do(params, decision):
        camp = (decision.get("entity_key") or "").split(":")[2]
        cl = client()
        prev = cl.get(camp, fields="status").get("status") or "ACTIVE"
        cl.post(camp, status=status)
        return {"campaign": camp, "previous_status": prev}
    return do


def _undo_status(payload, decision):
    client().post(payload["campaign"], status=payload["previous_status"])


def _budget(params, decision):
    cl = client()
    prev = {}
    for camp in (params["from"], params["to"]):
        prev[camp] = int(cl.get(camp, fields="daily_budget").get("daily_budget") or 0)
    if not prev[params["from"]]:
        raise RuntimeError("campaign has no daily budget (CBO off / lifetime budget): adjust on the platform")
    move = int(prev[params["from"]] * float(params["shift_pct"]) / 100)
    cl.post(params["from"], daily_budget=prev[params["from"]] - move)
    cl.post(params["to"], daily_budget=prev[params["to"]] + move)
    return {"previous": prev}


def _undo_budget(payload, decision):
    cl = client()
    for camp, amt in payload["previous"].items():
        cl.post(camp, daily_budget=amt)


def register() -> None:
    from marketing import content, engine, inbox
    engine.register_executor("meta", "pause", _status("PAUSED"), _undo_status)
    engine.register_executor("meta", "pause_spend_spike", _status("PAUSED"), _undo_status)
    engine.register_executor("meta", "resume", _status("ACTIVE"), _undo_status)
    engine.register_executor("meta", "shift_budget", _budget, _undo_budget)
    content.register_publisher("facebook", publish_facebook)
    content.register_publisher("instagram", publish_instagram)
    for ch in ("facebook_comment", "instagram_comment", "messenger", "instagram_dm"):
        inbox.register_sender(ch, _reply)
