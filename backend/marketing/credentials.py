"""Integration credentials (MARKETING_PLAN working rules: "Secrets").

The owner enters tokens on Admin > Marketing > Integrations. Secret fields are
Fernet-encrypted with MARKETING_SECRETS_KEY (in backend/.env, never in the DB)
before they are stored; nothing here ever returns, logs or prints a secret.
status() shows only which fields are set. secrets() decrypts for the server-side
API clients. If the key is missing, storing is refused (a generated throwaway
key would make every stored token unreadable after a restart).

Collection: email_automation.integration_credentials, one doc per platform
({_id: platform}); `settings` holds the non-secret IDs (property IDs, sites,
customer / page / ad account IDs per BU).
"""
import os
from datetime import datetime
from typing import Any, Callable, Dict, Optional

KEY_ENV = "MARKETING_SECRETS_KEY"
COLLECTION = "integration_credentials"

# platform -> secret fields, settings fields (non-secret), what it unlocks
PLATFORMS: Dict[str, Dict[str, Any]] = {
    "google_service_account": {"label": "Google service account (GA4 + Search Console)",
                               "secrets": ["service_account_json"],
                               "settings": ["ga4_property_ids", "gsc_sites"], "plan": "3.2.2, 3.3.1"},
    "pagespeed": {"label": "PageSpeed Insights API key", "secrets": ["api_key"], "settings": ["urls"], "plan": "3.3.3"},
    "google_ads": {"label": "Google Ads API", "secrets": ["developer_token", "client_secret", "refresh_token"],
                   "settings": ["client_id", "login_customer_id", "customer_ids", "conversion_ids"], "plan": "3.4"},
    "linkedin": {"label": "LinkedIn (Community Management, Advertising, Lead Sync)",
                 "secrets": ["client_secret", "access_token", "refresh_token"],
                 "settings": ["client_id", "organization_ids", "ad_account_ids", "insight_partner_id"], "plan": "3.4, 3.5.1"},
    "meta": {"label": "Meta (Pages, Instagram, Lead Ads, Marketing API, Conversions API)",
             "secrets": ["system_user_token", "app_secret", "webhook_verify_token"],
             "settings": ["app_id", "page_ids", "instagram_ids", "ad_account_ids", "pixel_ids"], "plan": "3.4, 3.5.2"},
    "whatsapp": {"label": "WhatsApp Business Platform (Cloud API)", "secrets": ["access_token", "webhook_verify_token"],
                 "settings": ["waba_id", "phone_number_ids"], "plan": "3.5.3"},
    "quora": {"label": "Quora Ads (CSV import)", "secrets": [], "settings": ["pixel_ids", "csv_folder"], "plan": "3.4.2"},
}


class CredentialsUnavailable(RuntimeError):
    pass


def _fernet():
    key = os.getenv(KEY_ENV, "").strip()
    if not key:
        raise CredentialsUnavailable(f"{KEY_ENV} is not set on the server; tokens cannot be stored")
    from cryptography.fernet import Fernet
    return Fernet(key.encode())


def _col(gd: Optional[Callable] = None):
    if gd is None:
        from database import get_database as gd
    return gd("email_automation")[COLLECTION]


def status(gd: Optional[Callable] = None) -> Dict[str, Any]:
    """Per platform: which secret fields are set (True/False), the non-secret settings, health. No secrets."""
    docs = {d["_id"]: d for d in _col(gd).find({})}
    out = {}
    for p, spec in PLATFORMS.items():
        d = docs.get(p) or {}
        enc = d.get("secrets") or {}
        # the first listed secret is the one the platform cannot work without
        connected = bool(enc.get(spec["secrets"][0])) if spec["secrets"] else bool(d.get("settings"))
        out[p] = {"label": spec["label"], "plan": spec["plan"],
                  "secrets": {f: bool(enc.get(f)) for f in spec["secrets"]},
                  "settings": {f: (d.get("settings") or {}).get(f) for f in spec["settings"]},
                  "connected": connected,
                  "updated_at": d.get("updated_at"), "updated_by": d.get("updated_by"),
                  "last_ok_at": d.get("last_ok_at"), "last_error": d.get("last_error")}
    out["_key_configured"] = bool(os.getenv(KEY_ENV, "").strip())
    return out


def save(platform: str, *, secrets: Optional[Dict[str, str]] = None, settings: Optional[Dict[str, Any]] = None,
         actor: str, gd: Optional[Callable] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Blank secret values are ignored (keep the stored one); clear a secret with clear()."""
    spec = PLATFORMS.get(platform)
    if not spec:
        raise KeyError(f"unknown platform {platform!r}")
    secrets = {k: v for k, v in (secrets or {}).items() if isinstance(v, str) and v.strip()}
    bad = [k for k in secrets if k not in spec["secrets"]] + [k for k in (settings or {}) if k not in spec["settings"]]
    if bad:
        raise ValueError(f"unknown field(s) for {platform}: {', '.join(sorted(bad))}")
    now = now or datetime.utcnow()
    upd: Dict[str, Any] = {"updated_at": now, "updated_by": actor, "last_error": None}
    if secrets:
        f = _fernet()
        for k, v in secrets.items():
            upd[f"secrets.{k}"] = f.encrypt(v.strip().encode()).decode()
    for k, v in (settings or {}).items():
        upd[f"settings.{k}"] = v
    _col(gd).update_one({"_id": platform}, {"$set": upd, "$setOnInsert": {"created_at": now, "platform": platform}},
                        upsert=True)
    _audit(actor, "update", platform, f"secrets set: {sorted(secrets)}; settings: {sorted(settings or {})}")
    return status(gd)[platform]


def clear(platform: str, field: Optional[str], *, actor: str, gd: Optional[Callable] = None) -> Dict[str, Any]:
    """Remove one secret field, or the whole platform when field is None (disconnect)."""
    if platform not in PLATFORMS:
        raise KeyError(platform)
    col = _col(gd)
    if field is None:
        col.delete_one({"_id": platform})
    else:
        if field not in PLATFORMS[platform]["secrets"]:
            raise ValueError(field)
        col.update_one({"_id": platform}, {"$unset": {f"secrets.{field}": ""},
                                           "$set": {"updated_at": datetime.utcnow(), "updated_by": actor}})
    _audit(actor, "delete", platform, f"cleared {field or 'all'}")
    return status(gd)[platform]


def secrets(platform: str, gd: Optional[Callable] = None) -> Dict[str, Any]:
    """Decrypted secrets + settings for a server-side API client. Never send this to a browser or a log."""
    d = _col(gd).find_one({"_id": platform}) or {}
    enc = d.get("secrets") or {}
    out: Dict[str, Any] = {"settings": d.get("settings") or {}}
    if enc:
        f = _fernet()
        for k, v in enc.items():
            out[k] = f.decrypt(v.encode()).decode()
    return out


def mark(platform: str, *, ok: bool, error: Optional[str] = None, gd: Optional[Callable] = None) -> None:
    """An API client records its last successful call / last error (error text must not contain a secret)."""
    now = datetime.utcnow()
    _col(gd).update_one({"_id": platform}, {"$set": {"last_ok_at": now, "last_error": None} if ok else
                                            {"last_error": (error or "error")[:300], "last_error_at": now}})


def _audit(actor: str, action: str, platform: str, reason: str) -> None:
    try:
        from platform_core.audit import log_action
        log_action(actor=actor, action=action, entity_type="integration_credentials", entity_id=platform,
                   reason=reason, source="marketing_integrations")
    except Exception:
        pass
