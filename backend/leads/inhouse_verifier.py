"""
In-house email verification from our own evidence.

A mailbox check proper asks the recipient's mail server over SMTP (port 25);
DigitalOcean blocks outbound port 25 from our VM (tested 2026-09-28: gmail,
logixmx and outlook MX all time out), and the local language model cannot
know whether a mailbox exists. What we do have is our own history: 60k
outreach sends with 14k bounces, and every address that has ever written to
us. This module turns that into a verdict:

  valid     the address has written to us, or received our mail (sent 3+
            days ago) without bouncing
  invalid   the address bounced, or fails syntax / role / disposable / MX
  likely    it follows the local-part pattern (first.last, flast, ...) of at
            least PATTERN_MIN proven addresses at the same domain, and the
            domain's bounce rate is below RISKY_BOUNCE_RATE
  risky     the domain bounces at RISKY_BOUNCE_RATE or more
  unknown   no evidence either way

It records the verdict (verification_status "inhouse:<verdict>" plus the
evidence) and never sets `sendable` -- whether "likely" is good enough to
send to is the owner's decision, and sending is off for now.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

PATTERN_MIN = 2
RISKY_BOUNCE_RATE = 0.30
MIN_DOMAIN_SENDS = 5
BOUNCE_GRACE_DAYS = 3

_NONALPHA = re.compile(r"[^a-z]")


def _name_parts(name: str) -> Tuple[str, str]:
    parts = [_NONALPHA.sub("", p.lower()) for p in (name or "").split()]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return (parts[0] if parts else ""), ""
    return parts[0], parts[-1]


PATTERNS = {
    "first.last": lambda f, l: f"{f}.{l}",
    "firstlast": lambda f, l: f"{f}{l}",
    "flast": lambda f, l: f"{f[:1]}{l}",
    "f.last": lambda f, l: f"{f[:1]}.{l}",
    "first": lambda f, l: f,
    "first_last": lambda f, l: f"{f}_{l}",
    "last.first": lambda f, l: f"{l}.{f}",
    "firstl": lambda f, l: f"{f}{l[:1]}",
    "first.l": lambda f, l: f"{f}.{l[:1]}",
    "lastf": lambda f, l: f"{l}{f[:1]}",
}


def pattern_of(email: str, name: str) -> Optional[str]:
    """Which known pattern this address follows for this person, if any."""
    local = (email or "").split("@")[0].lower()
    f, l = _name_parts(name)
    if not f:
        return None
    if not l:
        return "first" if local == f else None
    for key, fn in PATTERNS.items():
        if fn(f, l) == local:
            return key
    return None


class Evidence:
    """What our history says about addresses and domains."""

    def __init__(self, client, now: Optional[datetime] = None):
        now = now or datetime.utcnow()
        t = client["torpedo"]
        self.bounced = set()
        self.delivered = set()
        dom_sent: Counter = Counter()
        dom_bounced: Counter = Counter()
        grace = now - timedelta(days=BOUNCE_GRACE_DAYS)
        for s in t["outreach_sends_v2"].find({}, {"email": 1, "status": 1, "sent_at": 1}):
            e = (s.get("email") or "").strip().lower()
            if "@" not in e:
                continue
            d = e.split("@")[1]
            dom_sent[d] += 1
            if s.get("status") == "bounced":
                self.bounced.add(e)
                dom_bounced[d] += 1
            elif isinstance(s.get("sent_at"), datetime) and s["sent_at"] <= grace:
                self.delivered.add(e)
        self.delivered -= self.bounced
        self.bounce_rate = {d: dom_bounced[d] / n for d, n in dom_sent.items() if n >= MIN_DOMAIN_SENDS}
        self.wrote_to_us = set(e.strip().lower() for e in client["torpedo_gmail"]["email_metadata"].distinct(
            "from_email", {"direction": "inbound"}) if isinstance(e, str))
        # Proven local-part patterns per domain, from addresses that worked.
        names = {}
        for l in t["outreach_leads_v2"].find({"email": {"$in": list(self.delivered)}}, {"email": 1, "name": 1}):
            names[(l.get("email") or "").lower()] = l.get("name") or ""
        self.patterns: Dict[str, Counter] = defaultdict(Counter)
        for e, n in names.items():
            p = pattern_of(e, n)
            if p:
                self.patterns[e.split("@")[1]][p] += 1


def verify(email: str, name: str, ev: Evidence) -> Dict[str, Any]:
    from scripts.verification_gate import free_checks
    e = (email or "").strip().lower()
    free = free_checks(e)
    if free["free_check_result"] != "pass":
        return {"verdict": "invalid", "why": free["free_check_reason"]}
    if e in ev.bounced:
        return {"verdict": "invalid", "why": "bounced before"}
    if e in ev.wrote_to_us:
        return {"verdict": "valid", "why": "has written to us"}
    if e in ev.delivered:
        return {"verdict": "valid", "why": "delivered before without a bounce"}
    d = e.split("@")[1]
    rate = ev.bounce_rate.get(d)
    if rate is not None and rate >= RISKY_BOUNCE_RATE:
        return {"verdict": "risky", "why": f"domain bounce rate {rate:.0%}"}
    p = pattern_of(e, name)
    proven = ev.patterns.get(d, Counter())
    if p and proven.get(p, 0) >= PATTERN_MIN:
        return {"verdict": "likely", "why": f"matches {p}, proven by {proven[p]} delivered addresses at {d}"}
    if proven and p and p not in proven:
        return {"verdict": "unknown", "why": f"{d} uses {proven.most_common(1)[0][0]}, this address is {p}"}
    return {"verdict": "unknown", "why": "no evidence for this address or domain"}


def score_outreach_leads(client, statuses: Iterable[str] = ("not_started", "skipped_gate"),
                         apply: bool = False) -> Dict[str, Any]:
    """Verdict for every outreach row in these states. Writes only with
    apply=True, and never touches `sendable`."""
    ev = Evidence(client)
    col = client["torpedo"]["outreach_leads_v2"]
    counts: Counter = Counter()
    samples: Dict[str, List[str]] = defaultdict(list)
    now = datetime.utcnow()
    for lead in col.find({"workflow_status": {"$in": list(statuses)}}, {"email": 1, "name": 1}):
        r = verify(lead.get("email"), lead.get("name"), ev)
        counts[r["verdict"]] += 1
        if len(samples[r["verdict"]]) < 4:
            samples[r["verdict"]].append(f"{lead.get('email')} — {r['why']}")
        if apply:
            col.update_one({"_id": lead["_id"]}, {"$set": {
                "inhouse_verification": {**r, "at": now},
                "verification_status_inhouse": f"inhouse:{r['verdict']}"}})
    return {"counts": dict(counts), "samples": dict(samples),
            "evidence": {"delivered": len(ev.delivered), "bounced": len(ev.bounced),
                         "wrote_to_us": len(ev.wrote_to_us), "domains_with_patterns": len(ev.patterns)}}
