"""
Email Validator Service for Outreach Pipeline.

Performs syntax validation, MX record checks (with 24h cache), and
role-based email filtering before sending or during ingestion.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Role-based local parts that should never receive outreach
ROLE_ADDRESSES = frozenset({
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
    "info", "support", "help", "admin", "webmaster", "postmaster",
    "hostmaster", "abuse", "security", "mailer-daemon", "root",
    "sales", "marketing", "billing", "accounts", "feedback",
    "newsletter", "unsubscribe", "bounce", "team",
})

# Known disposable/temp-mail domains. Not exhaustive — extend as new ones
# show up in bounce/complaint data.
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "yopmail.com", "trashmail.com", "throwaway.email", "temp-mail.org",
    "getnada.com", "sharklasers.com", "fakeinbox.com", "maildrop.cc",
    "dispostable.com", "mintemail.com", "mailnesia.com",
})

# Common local-part typos of free-mail domains -> corrected domain. This is
# for outreach lead data (someone fat-fingered their own gmail address),
# not for correcting AI-guessed corporate domains — those should fail
# closed (see domain_exists) rather than be "corrected".
TYPO_DOMAIN_CORRECTIONS = {
    "gmial.com": "gmail.com", "gmai.com": "gmail.com", "gmail.co": "gmail.com",
    "gmali.com": "gmail.com", "gmaill.com": "gmail.com", "gnail.com": "gmail.com",
    "yaho.com": "yahoo.com", "yahooo.com": "yahoo.com", "yaoo.com": "yahoo.com",
    "hotmial.com": "hotmail.com", "hotmal.com": "hotmail.com", "hotmai.com": "hotmail.com",
    "outlok.com": "outlook.com", "outllook.com": "outlook.com",
}

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)

# MX cache TTL
MX_CACHE_TTL_HOURS = int(os.getenv("MX_CACHE_TTL_HOURS", "24"))


def correct_typo_domain(email: str) -> Optional[str]:
    """
    Return a corrected email if the domain is a known typo of a major free
    provider, else None. Caller decides whether to auto-apply or just flag.
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        return None
    local, domain = email.split("@", 1)
    corrected = TYPO_DOMAIN_CORRECTIONS.get(domain)
    return f"{local}@{corrected}" if corrected else None


class EmailValidator:
    """Pre-send and ingestion-time email validation."""

    def __init__(self, db: Any):
        self.db = db
        self.mx_cache = db["email_mx_cache"]
        self._ensure_indexes()

    def _ensure_indexes(self):
        try:
            self.mx_cache.create_index("domain", unique=True)
            self.mx_cache.create_index("checked_at", expireAfterSeconds=MX_CACHE_TTL_HOURS * 3600)
        except Exception as e:
            logger.warning(f"MX cache index setup: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_before_send(self, email: str) -> Tuple[bool, str]:
        """
        Full validation before sending an email.
        Returns (is_valid, reason).
        """
        email = (email or "").strip().lower()

        # 1) Syntax
        if not EMAIL_REGEX.match(email):
            return False, "invalid_syntax"

        local_part, domain = email.split("@")

        # 2) Role-based
        if local_part in ROLE_ADDRESSES:
            return False, "role_address"

        # 3) Disposable domain
        if domain in DISPOSABLE_DOMAINS:
            return False, "disposable_domain"

        # 4) MX lookup
        has_mx = self._check_mx_cached(domain)
        if not has_mx:
            return False, "no_mx_records"

        return True, "ok"

    def validate_on_ingestion(self, email: str) -> Tuple[bool, str]:
        """
        Lightweight validation at ingestion time (syntax + role-based +
        disposable-domain). MX check is skipped to keep ingestion fast —
        it will be caught at send time by validate_before_send.
        """
        email = (email or "").strip().lower()

        if not EMAIL_REGEX.match(email):
            return False, "invalid_syntax"

        local_part, domain = email.split("@")

        if local_part in ROLE_ADDRESSES:
            return False, "role_address"

        if domain in DISPOSABLE_DOMAINS:
            return False, "disposable_domain"

        return True, "ok"

    def domain_exists(self, domain: str) -> bool:
        """
        Cheap existence check for a domain used only to gate whether we
        trust it as a company_domain (e.g. from an AI web-search enrichment
        step), before it's ever used to construct a predicted email.
        True if the domain has MX records OR resolves via A/AAAA (some
        domains route mail off an A record with no MX, which is valid).
        """
        domain = (domain or "").strip().lower()
        if not domain:
            return False
        if self._check_mx_cached(domain):
            return True
        return self._dns_a_lookup(domain)

    @staticmethod
    def _dns_a_lookup(domain: str) -> bool:
        try:
            import dns.resolver
            import dns.exception

            answers = dns.resolver.resolve(domain, "A", lifetime=5)
            return len(list(answers)) > 0
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.exception.Timeout):
            return False
        except Exception:
            logger.warning("dnspython not available — skipping A-record check")
            return True

    # ------------------------------------------------------------------
    # MX check with MongoDB cache
    # ------------------------------------------------------------------

    def _check_mx_cached(self, domain: str) -> bool:
        """Check MX records with 24h cache in MongoDB."""
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=MX_CACHE_TTL_HOURS)

        # Cache hit?
        cached = self.mx_cache.find_one({"domain": domain, "checked_at": {"$gte": cutoff}})
        if cached is not None:
            return cached.get("has_mx", False)

        # Cache miss — perform DNS lookup
        has_mx = self._dns_mx_lookup(domain)

        try:
            self.mx_cache.update_one(
                {"domain": domain},
                {"$set": {"domain": domain, "has_mx": has_mx, "checked_at": now}},
                upsert=True,
            )
        except Exception as e:
            logger.warning(f"MX cache write failed for {domain}: {e}")

        return has_mx

    @staticmethod
    def _dns_mx_lookup(domain: str) -> bool:
        """Perform a real DNS MX lookup using dnspython."""
        try:
            import dns.resolver
            import dns.exception

            answers = dns.resolver.resolve(domain, "MX", lifetime=5)
            return len(list(answers)) > 0
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.exception.Timeout):
            return False
        except Exception:
            # If dnspython is not installed, skip MX check
            logger.warning("dnspython not available — skipping MX check")
            return True
