"""LinkedIn (MARKETING_PLAN 3.4, 3.5.1) -- company pages only, official REST APIs; no personal-profile automation.

Integrations > LinkedIn: client_secret, access_token, refresh_token (secrets); client_id, organization_ids,
ad_account_ids, insight_partner_id, conversion_ids {"SFW": {"lead": "<conversion rule id>", ...}} (settings).
  import_daily        adAnalytics per campaign per day (spend in INR, clicks, leads), campaigns
  page_stats          organization share statistics -> social_metrics_daily (reach, engagement)
  upload_conversions  Conversions API with li_fat_id + hashed email; never twice; shadow until live
  fetch_lead_forms    Lead Gen Form responses (Lead Sync) -> CRM lead + inbox item
  publisher           company-page post (content calendar, approved items only)
  executors           pause / resume campaign with undo
Version header: LINKEDIN_API_VERSION (yyyymm; LinkedIn retires versions after a year).
"""
import os
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from marketing import ads_common, credentials, schema

VERSION = os.getenv("LINKEDIN_API_VERSION", "202410")
API = "https://api.linkedin.com/rest"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"


class NotConfigured(RuntimeError):
    pass


class Client:
    def __init__(self, cred: Dict[str, Any], http=None):
        if not cred.get("access_token"):
            raise NotConfigured("LinkedIn: access token needed (Integrations)")
        self.c, self.s = cred, cred.get("settings") or {}
        self.http = http or __import__("requests")
        self.token = cred["access_token"]

    def h(self, **extra) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "LinkedIn-Version": VERSION, "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json", **extra}

    def _call(self, method: str, path: str, *, raw_query: str = "", json=None, headers=None):
        url = f"{API}/{path}" + (f"?{raw_query}" if raw_query else "")
        r = getattr(self.http, method)(url, json=json, headers=headers or self.h(), timeout=60) if method != "get" else \
            self.http.get(url, headers=headers or self.h(), timeout=60)
        if r.status_code == 401 and self.c.get("refresh_token") and not getattr(self, "_refreshed", False):
            self._refresh()
            return self._call(method, path, raw_query=raw_query, json=json, headers=None)
        if r.status_code >= 400:
            raise RuntimeError(f"LinkedIn HTTP {r.status_code}: {str(getattr(r, 'text', ''))[:250]}")
        return r

    def _refresh(self):
        self._refreshed = True
        r = self.http.post(TOKEN_URL, data={"grant_type": "refresh_token", "refresh_token": self.c["refresh_token"],
                                            "client_id": self.s.get("client_id"), "client_secret": self.c.get("client_secret")}, timeout=30)
        d = r.json()
        if r.status_code >= 400 or not d.get("access_token"):
            raise RuntimeError("LinkedIn token refresh failed: reconnect on Integrations")
        self.token = d["access_token"]
        try:
            credentials.save("linkedin", secrets={"access_token": self.token}, actor="linkedin_refresh")
        except Exception:
            pass

    def get(self, path: str, raw_query: str = "") -> Dict[str, Any]:
        return self._call("get", path, raw_query=raw_query).json()

    def post(self, path: str, body: Dict[str, Any], **headers):
        return self._call("post", path, json=body, headers=self.h(**headers))


def client(gd=None, http=None) -> Client:
    return Client(credentials.secrets("linkedin", gd), http)


def per_bu(setting) -> List[tuple]:
    return [(bu, str(x)) for bu, v in (setting or {}).items() for x in (v if isinstance(v, list) else [v]) if x]


def _date(d: datetime) -> str:
    return f"(year:{d.year},month:{d.month},day:{d.day})"


def _urn_id(urn: str) -> str:
    return str(urn).rsplit(":", 1)[-1]


def import_daily(gd: Optional[Callable] = None, *, days: int = 3, now: Optional[datetime] = None, cl: Optional[Client] = None) -> Dict[str, Any]:
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    try:
        cl = cl or client(gd)
    except NotConfigured as e:
        return {"skipped": str(e)}
    start, end = now - timedelta(days=days), now - timedelta(days=1)
    rates = ads_common.fx(gd)
    rep: Dict[str, Any] = {"accounts": {}, "errors": []}
    for bu, acc in per_bu(cl.s.get("ad_account_ids")):
        try:
            a = cl.get(f"adAccounts/{acc}")
            ccy = a.get("currency") or "INR"
            ads_common.store_entities(gd, "linkedin", "ad_accounts", "account_id", [{
                "account_id": acc, "name": a.get("name"), "currency": ccy, "bu": bu, "status": a.get("status"),
                "billing_problem": a.get("status") in ("BILLING_HOLD", "CANCELED")}], now=now)
            camps = cl.get(f"adAccounts/{acc}/adCampaigns", "q=search").get("elements") or []
            ads_common.store_entities(gd, "linkedin", "ad_campaigns", "campaign_id", [{
                "campaign_id": str(c.get("id")), "name": c.get("name"), "status": c.get("status"), "bu": bu, "account_id": acc,
                "daily_budget": (c.get("dailyBudget") or {}).get("amount")} for c in camps], now=now)
            q = ("q=analytics&pivot=CAMPAIGN&timeGranularity=DAILY"
                 f"&dateRange=(start:{_date(start)},end:{_date(end)})"
                 f"&accounts=List({quote(f'urn:li:sponsoredAccount:{acc}', safe='')})"
                 "&fields=dateRange,pivotValues,impressions,clicks,costInLocalCurrency,oneClickLeads,externalWebsiteConversions,approximateMemberReach")
            rows = []
            for e in cl.get("adAnalytics", q).get("elements") or []:
                s = (e.get("dateRange") or {}).get("start") or {}
                cid = _urn_id((e.get("pivotValues") or [""])[0])
                leads = float(e.get("oneClickLeads") or 0) + float(e.get("externalWebsiteConversions") or 0)
                rows.append({"level": "campaign", "entity_id": cid, "campaign_id": cid, "bu": bu,
                             "date": f"{s.get('year')}-{int(s.get('month', 1)):02d}-{int(s.get('day', 1)):02d}",
                             "spend_inr": ads_common.to_inr(float(e.get("costInLocalCurrency") or 0), ccy, rates),
                             "impressions": float(e.get("impressions") or 0), "clicks": float(e.get("clicks") or 0),
                             "reach": float(e.get("approximateMemberReach") or 0), "conversions": leads, "platform_leads": leads})
            rep["accounts"][acc] = {"bu": bu, "rows": ads_common.store_metrics(gd, "linkedin", rows, now=now), "campaigns": len(camps)}
        except Exception as e:
            rep["errors"].append(f"{acc}: {str(e)[:200]}")
    rep["page_stats"] = page_stats(gd, cl=cl, now=now, days=days)
    rep["crm_joined"] = ads_common.attach_crm_outcomes(gd, "linkedin", since=now - timedelta(days=max(days, 30)), now=now)
    credentials.mark("linkedin", ok=not rep["errors"], error="; ".join(rep["errors"])[:300] or None, gd=gd)
    return rep


def page_stats(gd: Callable, *, cl: Client, now: datetime, days: int = 3) -> int:
    n = 0
    for bu, org in per_bu(cl.s.get("organization_ids")):
        s, e = int((now - timedelta(days=days)).timestamp() * 1000), int(now.timestamp() * 1000)
        q = (f"q=organizationalEntity&organizationalEntity={quote(f'urn:li:organization:{org}', safe='')}"
             f"&timeIntervals=(timeRange:(start:{s},end:{e}),timeGranularityType:DAY)")
        for el in cl.get("organizationalEntityShareStatistics", q).get("elements") or []:
            st = el.get("totalShareStatistics") or {}
            day = datetime.utcfromtimestamp(((el.get("timeRange") or {}).get("start") or 0) / 1000).strftime("%Y-%m-%d")
            eng = sum(float(st.get(k) or 0) for k in ("likeCount", "commentCount", "shareCount", "clickCount"))
            doc = {"platform": "linkedin", "entity_id": f"org:{org}", "date": day, "reach": float(st.get("uniqueImpressionsCount") or 0),
                   "impressions": float(st.get("impressionCount") or 0), "engagement": eng, "clicks": float(st.get("clickCount") or 0)}
            f, u = schema.upsert_ops(doc, ["platform", "entity_id", "date"], bu=bu, source="linkedin", now=now)
            gd(schema.DB)["social_metrics_daily"].update_one(f, u, upsert=True)
            n += 1
    return n


def upload_conversions(gd: Optional[Callable] = None, *, cfg: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None,
                       cl: Optional[Client] = None) -> Dict[str, Any]:
    if gd is None:
        from database import get_database as gd
    if cfg is None:
        from platform_core import config_store
        cfg = config_store.get("marketing")
    now = now or datetime.utcnow()
    pend = ads_common.pending_conversions(gd, "linkedin", id_keys=["li_fat_id"], now=now)
    rep = {"pending": len(pend), "sent": 0, "shadow": 0, "errors": []}
    if not pend:
        return rep
    if not ads_common.conversions_live(cfg, "linkedin"):
        for p in pend:
            ads_common.record_upload(gd, p, status="shadow", now=now)
        rep["shadow"] = len(pend)
        return rep
    try:
        cl = cl or client(gd)
    except NotConfigured as e:
        return {**rep, "skipped": str(e)}
    rules = cl.s.get("conversion_ids") or {}
    for p in pend:
        rule = (rules.get(p.get("bu")) or {}).get(p["event"])
        if not rule:
            ads_common.record_upload(gd, p, status="failed", response="no conversion rule for this BU+event", now=now)
            rep["errors"].append(f"{p['lead_id']} {p['event']}: no conversion rule")
            continue
        ids = [{"idType": "LINKEDIN_FIRST_PARTY_ADS_TRACKING_UUID", "idValue": p["click_id"]}]
        if p.get("email_sha256"):
            ids.append({"idType": "SHA256_EMAIL", "idValue": p["email_sha256"]})
        body = {"conversion": f"urn:lla:llaPartnerConversion:{rule}", "conversionHappenedAt": int(p["at"].timestamp() * 1000),
                "user": {"userIds": ids}, "eventId": f"{p['lead_id']}:{p['event']}"}
        if p["event"] == "won" and p.get("value_inr"):
            body["conversionValue"] = {"currencyCode": "INR", "amount": str(p["value_inr"])}
        try:
            cl.post("conversionEvents", body)
            ads_common.record_upload(gd, p, status="sent", now=now)
            rep["sent"] += 1
        except Exception as e:
            ads_common.record_upload(gd, p, status="failed", response=str(e), now=now)
            rep["errors"].append(str(e)[:120])
    return rep


def fetch_lead_forms(gd: Optional[Callable] = None, *, now: Optional[datetime] = None, cl: Optional[Client] = None, days: int = 2) -> Dict[str, Any]:
    """Lead Sync: sponsored lead form responses -> CRM lead (dedupe by email) + inbox (idempotent per response id)."""
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    try:
        cl = cl or client(gd)
    except NotConfigured as e:
        return {"skipped": str(e)}
    from marketing import inbox
    rep = {"fetched": 0, "errors": []}
    since = int((now - timedelta(days=days)).timestamp() * 1000)
    for bu, acc in per_bu(cl.s.get("ad_account_ids")):
        try:
            q = (f"q=owner&owner=(sponsoredAccount:{quote(f'urn:li:sponsoredAccount:{acc}', safe='')})"
                 f"&leadType=(leadType:SPONSORED)&submittedAtTimeRange=(start:{since},end:{int(now.timestamp() * 1000)})")
            for el in cl.get("leadFormResponses", q).get("elements") or []:
                answers = [((a.get("answerDetails") or {}).get("textQuestionAnswer") or {}).get("answer")
                           for a in ((el.get("formResponse") or {}).get("answers") or [])]
                answers = [a for a in answers if a]
                email = next((a.strip().lower() for a in answers if re.match(r"[^@\s]+@[^@\s]+\.[a-z]{2,}$", a.strip(), re.I)), "")
                rid = str(el.get("id"))
                crm = gd("crm_db")["leads"]
                if email and not crm.find_one({"email": email}):
                    crm.insert_one({"email": email, "source": "linkedin_lead_form", "bu": bu, "bus": [bu], "status": "new",
                                    "intent": "positive_inbound", "created_at": now, "updated_at": now,
                                    "metadata": {"source": "linkedin_lead_form", "response_id": rid, "campaign": el.get("campaign")}})
                inbox.ingest(gd, channel="linkedin_lead_form", external_id=rid, bu=bu, text="; ".join(a for a in answers if a.lower() != email),
                             author={"email": email}, kind="lead_form", sender_type="client")
                rep["fetched"] += 1
        except Exception as e:
            rep["errors"].append(f"{acc}: {str(e)[:150]}")
    return rep


def publish(item: Dict[str, Any]) -> Dict[str, Any]:
    cl = client()
    org = dict(per_bu(cl.s.get("organization_ids"))).get(item["bu"])
    if not org:
        raise RuntimeError(f"no LinkedIn page for {item['bu']}")
    text = (item.get("body") or "") + ("\n\n" + " ".join(item.get("hashtags") or []) if item.get("hashtags") else "")
    body = {"author": f"urn:li:organization:{org}", "commentary": text[:3000], "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
    r = cl.post("posts", body)
    pid = (getattr(r, "headers", {}) or {}).get("x-restli-id")
    return {"post_id": pid, "url": f"https://www.linkedin.com/feed/update/{pid}" if pid else None}


def _status(status):
    def do(params, decision):
        camp = (decision.get("entity_key") or "").split(":")[2]
        cl = client()
        acc = dict(per_bu(cl.s.get("ad_account_ids"))).get(decision.get("bu"))
        prev = cl.get(f"adAccounts/{acc}/adCampaigns/{camp}").get("status") or "ACTIVE"
        cl.post(f"adAccounts/{acc}/adCampaigns/{camp}", {"patch": {"$set": {"status": status}}}, **{"X-RestLi-Method": "PARTIAL_UPDATE"})
        return {"account": acc, "campaign": camp, "previous_status": prev}
    return do


def _undo(payload, decision):
    client().post(f"adAccounts/{payload['account']}/adCampaigns/{payload['campaign']}",
                  {"patch": {"$set": {"status": payload["previous_status"]}}}, **{"X-RestLi-Method": "PARTIAL_UPDATE"})


def register() -> None:
    from marketing import content, engine
    engine.register_executor("linkedin", "pause", _status("PAUSED"), _undo)
    engine.register_executor("linkedin", "pause_spend_spike", _status("PAUSED"), _undo)
    engine.register_executor("linkedin", "resume", _status("ACTIVE"), _undo)
    content.register_publisher("linkedin", publish)
