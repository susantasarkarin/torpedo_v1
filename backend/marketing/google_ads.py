"""Google Ads (MARKETING_PLAN 3.4): daily import, offline conversions, Decision Engine write actions.

REST + GAQL (googleAds:searchStream). Credentials on Integrations > Google Ads: developer_token,
client_secret, refresh_token (secrets); client_id, login_customer_id (MCC), customer_ids
{"SFW": "1234567890", ...}, conversion_ids {"SFW": {"lead": "customers/123/conversionActions/456", ...}}.
API version: GOOGLE_ADS_API_VERSION (default below) -- Google sunsets versions yearly.

Recommended tracking template on every account: {lpurl}?utm_source=google&utm_medium=cpc&utm_id={campaignid}
&utm_campaign={_campaign} so CRM leads join to campaigns (ads_common.attach_crm_outcomes).
Write actions (pause / resume / budget / target CPA / negatives) are registered as engine executors;
they run only when the engine allows (live mode + action live + autonomy + guardrails) and return an undo payload.
"""
import os
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from marketing import ads_common, credentials, schema

API_VERSION = os.getenv("GOOGLE_ADS_API_VERSION", "v19")
BASE = f"https://googleads.googleapis.com/{API_VERSION}"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class NotConfigured(RuntimeError):
    pass


def _requests():
    import requests
    return requests


class Client:
    def __init__(self, cred: Dict[str, Any], http=None):
        self.c, self.s = cred, cred.get("settings") or {}
        self.http = http or _requests()
        if not (cred.get("developer_token") and cred.get("refresh_token") and self.s.get("client_id") and cred.get("client_secret")):
            raise NotConfigured("Google Ads: developer token, OAuth client and refresh token needed (Integrations)")
        self._tok, self._exp = None, datetime.min

    def token(self) -> str:
        if not self._tok or datetime.utcnow() >= self._exp:
            r = self.http.post(TOKEN_URL, data={"grant_type": "refresh_token", "refresh_token": self.c["refresh_token"],
                                                "client_id": self.s["client_id"], "client_secret": self.c["client_secret"]}, timeout=30)
            d = _ok(r)
            self._tok, self._exp = d["access_token"], datetime.utcnow() + timedelta(seconds=int(d.get("expires_in", 3600)) - 120)
        return self._tok

    def headers(self) -> Dict[str, str]:
        h = {"Authorization": f"Bearer {self.token()}", "developer-token": self.c["developer_token"], "Content-Type": "application/json"}
        if self.s.get("login_customer_id"):
            h["login-customer-id"] = str(self.s["login_customer_id"]).replace("-", "")
        return h

    def search(self, cid: str, gaql: str) -> List[Dict[str, Any]]:
        r = self.http.post(f"{BASE}/customers/{cid}/googleAds:searchStream", json={"query": gaql}, headers=self.headers(), timeout=120)
        return [row for batch in _ok(r) for row in batch.get("results", [])]

    def mutate(self, cid: str, service: str, operations: List[Dict[str, Any]], **extra) -> Dict[str, Any]:
        r = self.http.post(f"{BASE}/customers/{cid}/{service}:mutate", json={"operations": operations, **extra},
                           headers=self.headers(), timeout=60)
        return _ok(r)

    def post(self, cid: str, method: str, body: Dict[str, Any]) -> Dict[str, Any]:
        r = self.http.post(f"{BASE}/customers/{cid}:{method}", json=body, headers=self.headers(), timeout=60)
        return _ok(r)


def _ok(r):
    if getattr(r, "status_code", 200) >= 400:
        try:
            err = r.json().get("error", {})
            msg = err.get("message") or str(err)
        except Exception:
            msg = getattr(r, "text", "")
        raise RuntimeError(f"Google Ads HTTP {r.status_code}: {str(msg)[:250]}")
    return r.json()


def customers(settings: Dict[str, Any]) -> List[tuple]:
    out = []
    for bu, v in (settings.get("customer_ids") or {}).items():
        for cid in (v if isinstance(v, list) else [v]):
            if cid:
                out.append((bu, str(cid).replace("-", "")))
    return out


def client(gd=None, http=None) -> Client:
    return Client(credentials.secrets("google_ads", gd), http)


def _m(row, *path, default=0):
    cur = row
    for p in path:
        cur = (cur or {}).get(p)
    return cur if cur is not None else default


def import_daily(gd: Optional[Callable] = None, *, days: int = 3, today_only: bool = False, now: Optional[datetime] = None,
                 cl: Optional[Client] = None) -> Dict[str, Any]:
    """days: re-read the last N full days (conversions settle late). today_only: the hourly spend / pacing pass."""
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    try:
        cl = cl or client(gd)
    except NotConfigured as e:
        return {"skipped": str(e)}
    ist_today = (now + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    start, end = ((ist_today, ist_today) if today_only else
                  ((now - timedelta(days=days)).strftime("%Y-%m-%d"), (now - timedelta(days=1)).strftime("%Y-%m-%d")))
    window = f"segments.date BETWEEN '{start}' AND '{end}'"
    rates = ads_common.fx(gd)
    rep: Dict[str, Any] = {"window": [start, end], "accounts": {}, "errors": []}
    for bu, cid in customers(cl.s):
        try:
            cur = (cl.search(cid, "SELECT customer.currency_code, customer.descriptive_name FROM customer") or [{}])[0].get("customer", {})
            ccy = cur.get("currencyCode") or "INR"
            ads_common.store_entities(gd, "google", "ad_accounts", "account_id",
                                      [{"account_id": cid, "name": cur.get("descriptiveName"), "currency": ccy, "bu": bu}], now=now)
            inr = lambda micros: ads_common.to_inr(int(micros or 0) / 1e6, ccy, rates)
            rows, camps, ads = [], [], []
            for r in cl.search(cid, "SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type, "
                                    "campaign_budget.resource_name, campaign_budget.amount_micros, campaign.primary_status, "
                                    "segments.date, metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions, "
                                    f"metrics.search_impression_share FROM campaign WHERE {window}"):
                c = r.get("campaign", {})
                camps.append({"campaign_id": c.get("id"), "name": c.get("name"), "status": c.get("status"), "bu": bu, "account_id": cid,
                              "channel": c.get("advertisingChannelType"), "primary_status": c.get("primaryStatus"),
                              "budget_resource": _m(r, "campaignBudget", "resourceName", default=None),
                              "daily_budget_inr": inr(_m(r, "campaignBudget", "amountMicros")),
                              "learning_phase": c.get("primaryStatus") == "LEARNING"})
                rows.append({"level": "campaign", "entity_id": c.get("id"), "campaign_id": c.get("id"), "name": c.get("name"),
                             "date": _m(r, "segments", "date", default=None), "bu": bu, "spend_inr": inr(_m(r, "metrics", "costMicros")),
                             "impressions": float(_m(r, "metrics", "impressions")), "clicks": float(_m(r, "metrics", "clicks")),
                             "conversions": float(_m(r, "metrics", "conversions")),
                             "impression_share": _m(r, "metrics", "searchImpressionShare", default=None)})
            for r in cl.search(cid, "SELECT ad_group.id, ad_group.name, campaign.id, segments.date, metrics.cost_micros, "
                                    f"metrics.impressions, metrics.clicks, metrics.conversions FROM ad_group WHERE {window}"):
                g = r.get("adGroup", {})
                rows.append({"level": "ad_group", "entity_id": g.get("id"), "group_id": g.get("id"), "campaign_id": _m(r, "campaign", "id", default=None),
                             "name": g.get("name"), "date": _m(r, "segments", "date", default=None), "bu": bu,
                             "spend_inr": inr(_m(r, "metrics", "costMicros")), "impressions": float(_m(r, "metrics", "impressions")),
                             "clicks": float(_m(r, "metrics", "clicks")), "conversions": float(_m(r, "metrics", "conversions"))})
            for r in cl.search(cid, "SELECT ad_group_ad.ad.id, ad_group_ad.ad.name, ad_group_ad.status, ad_group_ad.policy_summary.approval_status, "
                                    "ad_group.id, campaign.id, segments.date, metrics.cost_micros, metrics.impressions, metrics.clicks, "
                                    f"metrics.conversions FROM ad_group_ad WHERE {window}"):
                a = _m(r, "adGroupAd", "ad", default={})
                ads.append({"ad_id": a.get("id"), "name": a.get("name"), "group_id": _m(r, "adGroup", "id", default=None),
                            "campaign_id": _m(r, "campaign", "id", default=None), "bu": bu, "status": _m(r, "adGroupAd", "status", default=None),
                            "review_status": _m(r, "adGroupAd", "policySummary", "approvalStatus", default=None)})
                rows.append({"level": "ad", "entity_id": a.get("id"), "group_id": _m(r, "adGroup", "id", default=None),
                             "campaign_id": _m(r, "campaign", "id", default=None), "name": a.get("name"), "date": _m(r, "segments", "date", default=None),
                             "bu": bu, "spend_inr": inr(_m(r, "metrics", "costMicros")), "impressions": float(_m(r, "metrics", "impressions")),
                             "clicks": float(_m(r, "metrics", "clicks")), "conversions": float(_m(r, "metrics", "conversions"))})
            terms = []
            for r in cl.search(cid, "SELECT search_term_view.search_term, campaign.id, segments.date, metrics.cost_micros, "
                                    f"metrics.clicks, metrics.conversions FROM search_term_view WHERE {window}"):
                terms.append({"campaign_id": _m(r, "campaign", "id", default=None), "term": _m(r, "searchTermView", "searchTerm", default=""),
                              "date": _m(r, "segments", "date", default=None), "bu": bu, "platform": "google",
                              "spend_inr": inr(_m(r, "metrics", "costMicros")), "clicks": float(_m(r, "metrics", "clicks")),
                              "leads": float(_m(r, "metrics", "conversions"))})     # platform conversions = lead proxy per term
            uniq = {c["campaign_id"]: c for c in camps}
            ads_common.store_entities(gd, "google", "ad_campaigns", "campaign_id", uniq.values(), now=now)
            ads_common.store_entities(gd, "google", "ads", "ad_id", {a["ad_id"]: a for a in ads}.values(), now=now)
            n = ads_common.store_metrics(gd, "google", rows, now=now)
            for t in terms:
                f, u = schema.upsert_ops(t, ["campaign_id", "term", "date"], bu=bu, source="google", now=now)
                gd(schema.DB)["search_terms"].update_one(f, u, upsert=True)
            rep["accounts"][cid] = {"bu": bu, "rows": n, "campaigns": len(uniq), "search_terms": len(terms), "currency": ccy}
        except Exception as e:
            rep["errors"].append(f"{cid}: {str(e)[:200]}")
    rep["crm_joined"] = ads_common.attach_crm_outcomes(gd, "google", since=now - timedelta(days=max(days, 30)), now=now)
    credentials.mark("google_ads", ok=not rep["errors"], error="; ".join(rep["errors"])[:300] or None, gd=gd)
    return rep


def upload_conversions(gd: Optional[Callable] = None, *, cfg: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None,
                       cl: Optional[Client] = None) -> Dict[str, Any]:
    """3.4.4: click conversions by GCLID (+ hashed email = Enhanced Conversions for Leads). Shadow until live."""
    if gd is None:
        from database import get_database as gd
    if cfg is None:
        from platform_core import config_store
        cfg = config_store.get("marketing")
    now = now or datetime.utcnow()
    pend = ads_common.pending_conversions(gd, "google", id_keys=["gclid", "gbraid", "wbraid"], now=now)
    live = ads_common.conversions_live(cfg, "google")
    rep = {"pending": len(pend), "sent": 0, "shadow": 0, "errors": []}
    if not pend:
        return rep
    if not live:
        for p in pend:
            ads_common.record_upload(gd, p, status="shadow", now=now)
        rep["shadow"] = len(pend)
        return rep
    try:
        cl = cl or client(gd)
    except NotConfigured as e:
        return {**rep, "skipped": str(e)}
    conv_ids = cl.s.get("conversion_ids") or {}
    accounts = dict((bu, cid) for bu, cid in customers(cl.s))
    for p in pend:
        action = (conv_ids.get(p.get("bu")) or {}).get(p["event"])
        cid = accounts.get(p.get("bu"))
        if not action or not cid:
            ads_common.record_upload(gd, p, status="failed", response="no conversion action / account for this BU+event", now=now)
            rep["errors"].append(f"{p['lead_id']} {p['event']}: no conversion action")
            continue
        ist = p["at"] + timedelta(hours=5, minutes=30)
        cv = {"conversionAction": action, "conversionDateTime": ist.strftime("%Y-%m-%d %H:%M:%S+05:30"),
              "conversionValue": p["value_inr"] or 0, "currencyCode": "INR", p["click_type"]: p["click_id"]}
        if p.get("email_sha256"):
            cv["userIdentifiers"] = [{"hashedEmail": p["email_sha256"]}]
        try:
            res = cl.post(cid, "uploadClickConversions", {"conversions": [cv], "partialFailure": True})
            bad = res.get("partialFailureError")
            ads_common.record_upload(gd, p, status="failed" if bad else "sent", response=bad or res, now=now)
            if bad:
                rep["errors"].append(str(bad)[:120])
            else:
                rep["sent"] += 1
        except Exception as e:
            ads_common.record_upload(gd, p, status="failed", response=str(e), now=now)
            rep["errors"].append(str(e)[:120])
    return rep


# ------------------------------------------------------------------ Decision Engine executors (3.4.6)
def _entity(decision) -> tuple:
    """('google:campaign:<id>' ...) -> (customer id for the decision's BU, campaign id)."""
    parts = (decision.get("entity_key") or "").split(":")
    cid = dict(customers(client().s)).get(decision.get("bu"))
    if not cid:
        raise RuntimeError(f"no Google Ads account for {decision.get('bu')}")
    return cid, parts[2] if len(parts) > 2 else None


def _set_status(status):
    def do(params, decision):
        cid, camp = _entity(decision)
        cl = client()
        prev = (cl.search(cid, f"SELECT campaign.status FROM campaign WHERE campaign.id = {int(camp)}") or [{}])[0].get("campaign", {}).get("status")
        cl.mutate(cid, "campaigns", [{"update": {"resourceName": f"customers/{cid}/campaigns/{camp}", "status": status}, "updateMask": "status"}])
        return {"customer": cid, "campaign": camp, "previous_status": prev or "ENABLED"}
    return do


def _undo_status(payload, decision):
    client().mutate(payload["customer"], "campaigns", [{"update": {"resourceName": f"customers/{payload['customer']}/campaigns/{payload['campaign']}",
                                                                   "status": payload["previous_status"]}, "updateMask": "status"}])


def _add_negatives(params, decision):
    cid, camp = _entity(decision)
    ops = [{"create": {"campaign": f"customers/{cid}/campaigns/{camp}", "negative": True,
                       "keyword": {"text": t, "matchType": (params.get("match_type") or "phrase").upper()}}} for t in params.get("terms") or []]
    res = client().mutate(cid, "campaignCriteria", ops)
    return {"customer": cid, "criteria": [r.get("resourceName") for r in res.get("results", [])]}


def _undo_negatives(payload, decision):
    if payload.get("criteria"):
        client().mutate(payload["customer"], "campaignCriteria", [{"remove": rn} for rn in payload["criteria"]])


def _budget(params, decision):
    """D1 shift: move shift_pct of the 'from' campaign's daily budget to the 'to' campaign (net zero)."""
    cid = dict(customers(client().s)).get(decision.get("bu"))
    cl = client()
    res = {}
    for camp in (params["from"], params["to"]):
        r = (cl.search(cid, f"SELECT campaign_budget.resource_name, campaign_budget.amount_micros FROM campaign WHERE campaign.id = {int(camp)}")
             or [{}])[0].get("campaignBudget", {})
        res[camp] = (r.get("resourceName"), int(r.get("amountMicros") or 0))
    move = int(res[params["from"]][1] * float(params["shift_pct"]) / 100)
    ops = [{"update": {"resourceName": res[params["from"]][0], "amountMicros": res[params["from"]][1] - move}, "updateMask": "amount_micros"},
           {"update": {"resourceName": res[params["to"]][0], "amountMicros": res[params["to"]][1] + move}, "updateMask": "amount_micros"}]
    cl.mutate(cid, "campaignBudgets", ops)
    return {"customer": cid, "previous": {rn: amt for rn, amt in res.values()}}


def _undo_budget(payload, decision):
    client().mutate(payload["customer"], "campaignBudgets", [{"update": {"resourceName": rn, "amountMicros": amt}, "updateMask": "amount_micros"}
                                                             for rn, amt in payload["previous"].items()])


def _target(params, decision):
    cid, camp = _entity(decision)
    cl = client()
    r = (cl.search(cid, f"SELECT campaign.maximize_conversions.target_cpa_micros FROM campaign WHERE campaign.id = {int(camp)}") or [{}])[0]
    prev = int(_m(r, "campaign", "maximizeConversions", "targetCpaMicros"))
    if not prev:
        raise RuntimeError("campaign has no target CPA to adjust")
    new = int(prev * (1 + float(params["change_pct"]) / 100))
    cl.mutate(cid, "campaigns", [{"update": {"resourceName": f"customers/{cid}/campaigns/{camp}", "maximizeConversions": {"targetCpaMicros": new}},
                                  "updateMask": "maximize_conversions.target_cpa_micros"}])
    return {"customer": cid, "campaign": camp, "previous_target_cpa_micros": prev}


def _undo_target(payload, decision):
    client().mutate(payload["customer"], "campaigns", [{"update": {"resourceName": f"customers/{payload['customer']}/campaigns/{payload['campaign']}",
                                                                   "maximizeConversions": {"targetCpaMicros": payload["previous_target_cpa_micros"]}},
                                                        "updateMask": "maximize_conversions.target_cpa_micros"}])


def register() -> None:
    from marketing import engine
    engine.register_executor("google", "pause", _set_status("PAUSED"), _undo_status)
    engine.register_executor("google", "pause_spend_spike", _set_status("PAUSED"), _undo_status)
    engine.register_executor("google", "resume", _set_status("ENABLED"), _undo_status)
    engine.register_executor("google", "add_negatives", _add_negatives, _undo_negatives)
    engine.register_executor("google", "shift_budget", _budget, _undo_budget)
    engine.register_executor("google", "adjust_target", _target, _undo_target)
