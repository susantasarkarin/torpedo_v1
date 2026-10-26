"""Audiences (MARKETING_PLAN 3.4.5), synced daily, consent and DND respected.

Customer lists (hashed emails, built in code):
  exclude_clients_dnd   existing clients (contacts of accounts that won or were invoiced) + every suppressed / DND
                        address -> excluded from prospecting campaigns
  seed_won_clients      contacts of accounts with a won project -> seed for lookalikes
Website retargeting (all visitors 30 d, high-intent pages, form abandoners) cannot be uploaded -- we hold no platform
IDs for visitors -- so they are defined as pixel-rule audiences on Meta (the pixel only runs after consent); on Google
and LinkedIn they are built in the platform UI from the consent-gated tags (sizes from web_tracking.runner).
Sync is shadow (sizes recorded) until mode = live and action_modes["audiences:<platform>"] = "live".
LinkedIn Matched Audiences needs its own API permission: listed, not synced.
"""
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from bson import ObjectId

from marketing import ads_common, schema

LISTS = ("exclude_clients_dnd", "seed_won_clients")


def _won_account_ids(crm, fin) -> set:
    ids = {str(o["account_id"]) for o in crm["opportunities"].find({"status": "won", "account_id": {"$ne": None}}, {"account_id": 1})}
    ids |= {str(c["crm_account_id"]) for c in fin["customers"].find({"crm_account_id": {"$nin": [None, ""]}}, {"crm_account_id": 1})}
    return ids


def build_lists(gd: Callable) -> Dict[str, Dict[str, List[str]]]:
    """{bu: {list_name: [sha256 emails]}}; bu None = all BUs (exclusions apply to every BU's prospecting)."""
    crm, fin = gd("crm_db"), gd("finance_db")
    won = _won_account_ids(crm, fin)
    oids = [ObjectId(a) for a in won if ObjectId.is_valid(a)] + list(won)
    by_bu: Dict[str, Dict[str, set]] = {}
    acc_bu = {str(a["_id"]): a.get("bu") for a in crm["accounts"].find({"_id": {"$in": oids}}, {"bu": 1})}
    clients = set()
    for c in crm["contacts"].find({"account_id": {"$in": oids}}, {"email": 1, "account_id": 1}):
        h = ads_common.sha256_email(c.get("email") or "")
        if not h:
            continue
        clients.add(h)
        bu = acc_bu.get(str(c["account_id"]))
        if bu in schema.BUS:
            by_bu.setdefault(bu, {}).setdefault("seed_won_clients", set()).add(h)
    dnd = set()
    try:
        from messaging import suppression
        for s in suppression._canonical().find({}, {"email": 1}):
            h = ads_common.sha256_email(s.get("email") or "")
            if h:
                dnd.add(h)
    except Exception:
        pass
    out = {bu: {k: sorted(v) for k, v in lists.items()} for bu, lists in by_bu.items()}
    excl = sorted(clients | dnd)
    for bu in schema.BUS:
        out.setdefault(bu, {})["exclude_clients_dnd"] = excl
        out[bu].setdefault("seed_won_clients", [])
    return out


def retargeting_rules(site: str) -> List[Dict[str, Any]]:
    """Meta website custom audiences (pixel rules) for one site."""
    return [
        {"name": "visitors_30d", "retention_days": 30, "rule": {"inclusions": {"operator": "or", "rules": [
            {"event_sources": [{"type": "pixel"}], "retention_seconds": 30 * 86400,
             "filter": {"operator": "and", "filters": [{"field": "url", "operator": "i_contains", "value": site}]}}]}}},
        {"name": "high_intent_30d", "retention_days": 30, "rule": {"inclusions": {"operator": "or", "rules": [
            {"event_sources": [{"type": "pixel"}], "retention_seconds": 30 * 86400,
             "filter": {"operator": "or", "filters": [{"field": "url", "operator": "i_contains", "value": p}
                                                       for p in ("/pricing", "/panel", "/rate", "/contact")]}}]}}},
    ]


def sync(gd: Optional[Callable] = None, *, cfg: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None,
         meta_cl=None, google_cl=None) -> Dict[str, Any]:
    if gd is None:
        from database import get_database as gd
    if cfg is None:
        from platform_core import config_store
        cfg = config_store.get("marketing")
    now = now or datetime.utcnow()
    lists = build_lists(gd)
    ea = gd(schema.DB)
    rep: Dict[str, Any] = {"lists": {bu: {k: len(v) for k, v in l.items()} for bu, l in lists.items()}, "synced": [], "errors": []}
    for bu, l in lists.items():
        for name, hashes in l.items():
            for plat in ("meta", "google"):
                live = cfg.get("mode") == "live" and (cfg.get("action_modes") or {}).get(f"audiences:{plat}") == "live"
                key = {"bu": bu, "platform": plat, "name": name}
                doc = ea["audiences"].find_one(key) or {}
                status, platform_id = "shadow", doc.get("platform_id")
                if live and hashes:
                    try:
                        platform_id = (_meta_sync if plat == "meta" else _google_sync)(bu, name, hashes, platform_id, meta_cl, google_cl)
                        status = "synced"
                        rep["synced"].append(f"{bu}/{plat}/{name}")
                    except Exception as e:
                        status = "error"
                        rep["errors"].append(f"{bu}/{plat}/{name}: {str(e)[:150]}")
                f, u = schema.upsert_ops({**key, "size": len(hashes), "status": status, "platform_id": platform_id,
                                          "last_sync_at": now if status == "synced" else doc.get("last_sync_at")},
                                         ["bu", "platform", "name"], bu=bu, source="audiences", now=now)
                ea["audiences"].update_one(f, u, upsert=True)
    return rep


def _meta_sync(bu, name, hashes, platform_id, meta_cl, google_cl):
    import json
    from marketing import meta
    cl = meta_cl or meta.client()
    act = dict(meta.per_bu(cl.s.get("ad_account_ids"))).get(bu)
    if not act:
        raise RuntimeError("no Meta ad account for this BU")
    act = meta._act(act)
    if not platform_id:
        platform_id = cl.post(f"{act}/customaudiences", name=f"Torpedo {bu} {name}", subtype="CUSTOM",
                              customer_file_source="USER_PROVIDED_ONLY", description="Synced daily by Torpedo (hashed emails)")["id"]
    sid = int(datetime.utcnow().timestamp())
    for i in range(0, len(hashes), 10000):
        batch = hashes[i:i + 10000]
        cl.post(f"{platform_id}/usersreplace", session=json.dumps({"session_id": sid, "batch_seq": i // 10000 + 1,
                                                                    "last_batch_flag": i + 10000 >= len(hashes)}),
                payload=json.dumps({"schema": ["EMAIL_SHA256"], "data": [[h] for h in batch]}))
    return platform_id


def _google_sync(bu, name, hashes, platform_id, meta_cl, google_cl):
    from marketing import google_ads
    cl = google_cl or google_ads.client()
    cid = dict(google_ads.customers(cl.s)).get(bu)
    if not cid:
        raise RuntimeError("no Google Ads account for this BU")
    if not platform_id:
        res = cl.mutate(cid, "userLists", [{"create": {"name": f"Torpedo {bu} {name}", "membershipLifeSpan": 10000,
                                                       "crmBasedUserList": {"uploadKeyType": "CONTACT_INFO"}}}])
        platform_id = res["results"][0]["resourceName"]
    r = cl.http.post(f"{google_ads.BASE}/customers/{cid}/offlineUserDataJobs:create",
                     json={"job": {"type": "CUSTOMER_MATCH_USER_LIST", "customerMatchUserListMetadata": {"userList": platform_id}}},
                     headers=cl.headers(), timeout=60)
    job = google_ads._ok(r)["resourceName"]
    # a daily REPLACE, not an append: the list mirrors today's clients / DND exactly
    ops = [{"removeAll": True}] + [{"create": {"userIdentifiers": [{"hashedEmail": h}]}} for h in hashes]
    for i in range(0, len(ops), 10000):
        cl.http.post(f"{google_ads.BASE}/{job}:addOperations", json={"operations": ops[i:i + 10000], "enablePartialFailure": True},
                     headers=cl.headers(), timeout=120)
    cl.http.post(f"{google_ads.BASE}/{job}:run", json={}, headers=cl.headers(), timeout=60)
    return platform_id
