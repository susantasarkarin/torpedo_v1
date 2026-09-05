"""
verify_hmac_signature — the D-08 fix, for real, not a stub.

The register: "The Cint outcome callback — the actual production complete/terminate/
quota-full handler — has no signature or HMAC verification at all, while the JSON
webhook endpoints in the same system do verify a signature header. A forged
`status=complete` redirect triggers crediting... with no fraud check." And D-23,
the closely related CPX finding: "CPX postback hash validation fails open... when
`CPX_SECRET_KEY` is unset, validation is silently skipped... the handler returns
HTTP 200 even on hash failure."

Both defects are the same shape: **missing verification, or verification that fails
open.** This function refuses both failure modes by construction — an unset/empty
secret is a configuration error (`SignatureConfigError`), never a silent skip, and a
mismatched signature is `SignatureInvalid`, never a return-200. `CallbackService`
(service.py) calls this before anything else in `handle_callback`, unconditionally.

`hmac.compare_digest` specifically (not `==`) — a naive string comparison leaks
timing information proportional to the number of matching leading bytes, letting an
attacker recover a valid signature byte-by-byte. Using it here, for a payout-gating
signal, is not a hypothetical hardening; it is the actual attack D-08 describes made
slightly harder to pull off blind.
"""

from __future__ import annotations

import hashlib
import hmac


class SignatureConfigError(Exception):
    """No secret configured. Never treated as 'skip verification' — the D-23 failure
    mode, refused here by raising instead of falling through to a default of True."""


class SignatureInvalid(Exception):
    """The computed signature does not match. Never a silent 200 — the D-08 failure
    mode."""


def verify_hmac_signature(*, payload: bytes, secret: str | None, signature_hex: str) -> None:
    if not secret:
        raise SignatureConfigError("no callback signing secret configured — refusing to process, not skipping verification")
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_hex):
        raise SignatureInvalid("callback signature does not match")
