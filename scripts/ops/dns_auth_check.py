"""Daily SPF / DKIM / DMARC check for the three sending domains (CRM plan 3.11, Checkpoint-1 A4).

For each domain it checks:
  SPF   exactly one v=spf1 TXT, includes _spf.google.com, every include resolves,
        total DNS-lookup terms <= 10 (RFC 7208)
  DKIM  google._domainkey TXT with a public key of >= 2048 bits
  DMARC _dmarc TXT with v=DMARC1, a p= policy and a rua= address
Appends one JSON line per run to LOG (default /var/log/campaign_platform/dns_auth_check.jsonl)
and prints a short summary. Read-only DNS queries; writes nothing to MongoDB.

Cron (root):  0 3 * * *  = 08:30 IST
"""
import base64
import json
import os
import sys
from datetime import datetime, timezone

import dns.resolver

DOMAINS = os.getenv("AUTH_CHECK_DOMAINS", "surveyfieldwork.com,cogentixresearch.com,bimwavesolutions.com").split(",")
DKIM_SELECTOR = os.getenv("AUTH_CHECK_DKIM_SELECTOR", "google")
LOG = os.getenv("AUTH_CHECK_LOG", "/var/log/campaign_platform/dns_auth_check.jsonl")
LOOKUP_TERMS = ("include:", "a", "a:", "mx", "mx:", "ptr", "exists:", "redirect=")

res = dns.resolver.Resolver()
res.lifetime = 10


def txt(name):
    try:
        return ["".join(p.decode() for p in r.strings) for r in res.resolve(name, "TXT")]
    except dns.resolver.NXDOMAIN:
        return None
    except (dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
        return []


def spf_lookups(domain, depth=0):
    """(lookup count, list of problems) for one SPF tree."""
    if depth > 10:
        return 0, ["include loop/too deep"]
    recs = txt(domain)
    if recs is None:
        return 0, [f"include {domain} does not exist (NXDOMAIN)"]
    spf = [r for r in recs if r.lower().startswith("v=spf1")]
    if not spf:
        return 0, [f"include {domain} has no SPF record"]
    n, probs = 0, []
    for term in spf[0].split()[1:]:
        t = term.lstrip("+-~?").lower()
        if t.startswith("include:") or t.startswith("redirect="):
            n += 1
            sub_n, sub_p = spf_lookups(t.split(":", 1)[1] if ":" in t else t.split("=", 1)[1], depth + 1)
            n += sub_n
            probs += sub_p
        elif t in ("a", "mx", "ptr") or t.startswith(("a:", "mx:", "ptr:", "exists:")):
            n += 1
    return n, probs


def check_spf(domain):
    recs = txt(domain) or []
    spf = [r for r in recs if r.lower().startswith("v=spf1")]
    out = {"records": spf, "problems": []}
    if len(spf) != 1:
        out["problems"].append(f"{len(spf)} SPF records (must be exactly 1)")
    if spf:
        if "include:_spf.google.com" not in spf[0].lower():
            out["problems"].append("missing include:_spf.google.com")
        n, probs = spf_lookups(domain)
        out["lookups"] = n
        out["problems"] += probs
        if n > 10:
            out["problems"].append(f"{n} DNS lookups (> 10)")
    out["pass"] = not out["problems"]
    return out


def check_dkim(domain):
    recs = txt(f"{DKIM_SELECTOR}._domainkey.{domain}") or []
    out = {"selector": DKIM_SELECTOR, "problems": []}
    rec = next((r for r in recs if "p=" in r), None)
    if not rec:
        out["problems"].append(f"no TXT at {DKIM_SELECTOR}._domainkey")
    else:
        key = dict(kv.strip().split("=", 1) for kv in rec.split(";") if "=" in kv).get("p", "")
        try:
            bits = (len(base64.b64decode(key)) - 38) * 8  # SubjectPublicKeyInfo overhead ~38 bytes
        except Exception:
            bits = 0
        out["key_bits_approx"] = bits
        if bits < 2000:
            out["problems"].append(f"key ~{bits} bits (< 2048)")
    out["pass"] = not out["problems"]
    return out


def check_dmarc(domain):
    recs = txt(f"_dmarc.{domain}") or []
    out = {"records": recs, "problems": []}
    d = [r for r in recs if r.upper().startswith("V=DMARC1")]
    if len(d) != 1:
        out["problems"].append(f"{len(d)} DMARC records (must be exactly 1)")
    else:
        tags = {k.strip().lower(): v.strip() for k, v in (kv.split("=", 1) for kv in d[0].split(";") if "=" in kv)}
        out["policy"] = tags.get("p")
        if tags.get("p") not in ("none", "quarantine", "reject"):
            out["problems"].append("missing/invalid p=")
        if not tags.get("rua"):
            out["problems"].append("no rua= reporting address")
    out["pass"] = not out["problems"]
    return out


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results = {}
    for d in DOMAINS:
        r = {"spf": check_spf(d), "dkim": check_dkim(d), "dmarc": check_dmarc(d)}
        r["pass"] = all(r[k]["pass"] for k in ("spf", "dkim", "dmarc"))
        results[d] = r
        flags = " ".join(f"{k.upper()}={'PASS' if r[k]['pass'] else 'FAIL'}" for k in ("spf", "dkim", "dmarc"))
        print(f"{d}: {flags}" + ("" if r["pass"] else "  -> " + "; ".join(p for k in ("spf", "dkim", "dmarc") for p in r[k]["problems"])))
    try:
        with open(LOG, "a") as f:
            f.write(json.dumps({"checked_at": now, "results": results}) + "\n")
    except OSError as e:
        print(f"could not write {LOG}: {e}", file=sys.stderr)
    return 0 if all(r["pass"] for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
