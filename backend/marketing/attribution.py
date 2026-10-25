"""Channels and attribution models (MARKETING_PLAN 3.8). Pure, computed in code.

A touchpoint is {kind, at, utm, click_ids, referrer, mail_token, ...}; kind is
visit | form | mail_out | mail_in | ad_click | social | chat | lead_form.
Only touchpoints at or before the conversion count. Models:
  first_touch, last_touch, last_non_direct (the dashboard default),
  position_based 40/20/40 (2 touches: 50/50; 1 touch: 100).
Revenue is the CRM's won / invoiced INR, never a platform-reported conversion.
"""
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

MODELS = ("first_touch", "last_touch", "last_non_direct", "position_based")
DEFAULT_MODEL = "last_non_direct"

SEARCH = ("google.", "bing.", "duckduckgo.", "yahoo.", "yandex.", "baidu.", "ecosia.")
SOCIAL = ("linkedin.", "lnkd.in", "facebook.", "fb.", "instagram.", "t.co", "twitter.", "x.com", "quora.", "youtube.",
          "reddit.", "whatsapp.", "wa.me")
PAID_SEARCH_MEDIUM = {"cpc", "ppc", "paid_search", "paidsearch", "sem"}
PAID_SOCIAL_MEDIUM = {"paid_social", "paidsocial", "social_paid", "cpm", "display", "paid"}
SOCIAL_MEDIUM = {"social", "organic_social", "social_organic"}
KIND_CHANNEL = {"mail_out": "email", "mail_in": "email", "social": "social", "chat": "whatsapp", "lead_form": "paid_social"}


def _host(url: str) -> str:
    return (urlparse(url or "").hostname or url or "").lower().removeprefix("www.")


def channel(tp: Dict[str, Any], own_hosts=()) -> str:
    if tp.get("kind") in KIND_CHANNEL:
        return KIND_CHANNEL[tp["kind"]]
    cid = tp.get("click_ids") or {}
    utm = tp.get("utm") or {}
    medium = str(utm.get("utm_medium") or "").lower()
    source = str(utm.get("utm_source") or "").lower()
    if cid.get("gclid") or cid.get("gbraid") or cid.get("wbraid") or medium in PAID_SEARCH_MEDIUM:
        return "paid_search"
    if cid.get("li_fat_id") or medium in PAID_SOCIAL_MEDIUM:      # fbclid alone is on organic FB clicks too
        return "paid_social"
    if medium == "email" or tp.get("mail_token"):
        return "email"
    if medium in ("organic", "seo") and any(source.startswith(s.rstrip(".")) for s in SEARCH):
        return "organic_search"
    if medium in SOCIAL_MEDIUM or (source and any(source.startswith(s.rstrip(".")) for s in SOCIAL)):
        return "social"
    if medium == "referral" or source:
        return "referral"
    ref = _host(tp.get("referrer") or "")
    if ref and ref not in own_hosts:
        if any(ref.startswith(s) or ("." + s) in ref for s in SEARCH):
            return "organic_search"
        if cid.get("fbclid") or any(ref.startswith(s) or ("." + s) in ref for s in SOCIAL):
            return "social"
        return "referral"
    return "direct"


def credits(tps: List[Dict[str, Any]], model: str) -> List[float]:
    """Weight per touchpoint (same order; tps sorted by time), summing to 1 (or empty)."""
    n = len(tps)
    if not n:
        return []
    w = [0.0] * n
    if model == "first_touch":
        w[0] = 1.0
    elif model == "last_touch":
        w[-1] = 1.0
    elif model == "last_non_direct":
        idx = next((i for i in range(n - 1, -1, -1) if tps[i]["channel"] != "direct"), n - 1)
        w[idx] = 1.0
    elif model == "position_based":
        if n == 1:
            w[0] = 1.0
        elif n == 2:
            w[0] = w[1] = 0.5
        else:
            w[0] = w[-1] = 0.4
            for i in range(1, n - 1):
                w[i] = 0.2 / (n - 2)
    else:
        raise ValueError(model)
    return w


def attribute(tps: List[Dict[str, Any]], conversion: Dict[str, Any], own_hosts=()) -> Dict[str, Any]:
    """conversion: {id, event (rfq|won|lead), at, value_inr}. -> per model: channel -> {credit, value_inr}."""
    at: Optional[datetime] = conversion.get("at")
    path = sorted([dict(t, channel=t.get("channel") or channel(t, own_hosts)) for t in tps
                   if isinstance(t.get("at"), datetime) and (at is None or t["at"] <= at)], key=lambda t: t["at"])
    value = float(conversion.get("value_inr") or 0)
    out: Dict[str, Any] = {"touches": len(path), "path": [t["channel"] for t in path], "models": {},
                           "days_to_convert": (at - path[0]["at"]).days if path and at else None}
    for m in MODELS:
        by: Dict[str, Dict[str, float]] = defaultdict(lambda: {"credit": 0.0, "value_inr": 0.0})
        for t, wt in zip(path, credits(path, m)):
            if wt:
                by[t["channel"]]["credit"] += round(wt, 6)
                by[t["channel"]]["value_inr"] += round(wt * value, 2)
        out["models"][m] = dict(by)
    return out
