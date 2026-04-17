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

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)

# MX cache TTL
MX_CACHE_TTL_HOURS = int(os.getenv("MX_CACHE_TTL_HOURS", "24"))


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

        # 2) Role-based
        local_part = email.split("@")[0]
        if local_part in ROLE_ADDRESSES:
            return False, "role_address"

        # 3) MX lookup
        domain = email.split("@")[1]
        has_mx = self._check_mx_cached(domain)
        if not has_mx:
            return False, "no_mx_records"

        return True, "ok"

    def validate_on_ingestion(self, email: str) -> Tuple[bool, str]:
        """
        Lightweight validation at ingestion time (syntax + role-based).
        MX check is skipped to keep ingestion fast — it will be caught
        at send time.
        """
        email = (email or "").strip().lower()

        if not EMAIL_REGEX.match(email):
            return False, "invalid_syntax"

        local_part = email.split("@")[0]
        if local_part in ROLE_ADDRESSES:
            return False, "role_address"

        return True, "ok"

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
