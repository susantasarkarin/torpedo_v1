"""
"Open in Chrome" for visitors in a vendor app's in-app browser (2026-10-18).

Research Desk's in-app (Android WebView) traffic dropped out of client surveys
twice as often as its normal mobile browser traffic (35% vs 17%, first
entries, last 30 days); Cint's in-app traffic did not (14% vs 16%), and every
visitor of both reached our redirect -- the loss is inside the client survey
running in that app's browser. Offering to continue in Chrome takes the
survey out of it.

Run as a split test: a stable half of eligible visitors (hash of the
respondent id) gets the offer, the other half the normal flow, and every step
is logged (traffic_flow_db.inapp_events) so the arms can be compared on
completes per landing. Some apps cannot hand a link to Chrome; the log shows
that too ("open_clicked" without a matching arrival).

Settings (backend/.env):
  IN_APP_OFFER_VENDORS   comma list of vendor ids (default "5068" = Research Desk; "" = off)
  IN_APP_OFFER_PERCENT   share of eligible visitors who get the offer (default 50)
"""
import hashlib
import os
import re
from datetime import datetime
from typing import Optional

WEBVIEW_UA = re.compile(r"; wv\)")
EVENTS = {"landing", "open_clicked", "continued"}
ARMS = {"offer", "control"}


def is_inapp(user_agent: str) -> bool:
    return bool(WEBVIEW_UA.search(user_agent or ""))


def offer_vendors() -> set:
    raw = os.getenv("IN_APP_OFFER_VENDORS")
    raw = "5068" if raw is None else raw
    return {v.strip() for v in raw.split(",") if v.strip()}


def offer_percent() -> int:
    try:
        return max(0, min(100, int(os.getenv("IN_APP_OFFER_PERCENT", "50"))))
    except ValueError:
        return 50


def arm_for(vendor_id: str, respondent_id: str, user_agent: str) -> Optional[str]:
    """"offer" | "control" for an eligible visitor, None for everyone else.
    Stable per respondent id, so a reload never switches arms."""
    vendor_id = str(vendor_id or "").strip()
    if not vendor_id or vendor_id not in offer_vendors() or not is_inapp(user_agent):
        return None
    key = (str(respondent_id or "").strip() or user_agent).encode()
    bucket = int(hashlib.sha1(key).hexdigest()[:8], 16) % 100
    return "offer" if bucket < offer_percent() else "control"


def clean_event(body: dict) -> Optional[dict]:
    """A loggable step event, or None when the body is not one."""
    if not isinstance(body, dict):
        return None
    event, arm = str(body.get("event") or ""), str(body.get("arm") or "")
    if event not in EVENTS or arm not in ARMS:
        return None
    return {"event": event, "arm": arm,
            "vendorId": str(body.get("vid") or "")[:20],
            "respondentId": str(body.get("rid") or "")[:100],
            "projectNo": str(body.get("pid") or "")[:20],
            "at": datetime.utcnow()}
