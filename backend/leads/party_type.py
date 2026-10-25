"""Who is this AI Database record to us? (owner, 2026-10-25)

    potential_client   a company that could buy from SFW / Cogentix / BIM
    client             already billed (finance customer / party_relationships client)
    vendor             sells to us: panel / sample companies, data tools, services
    role_mailbox       a shared or system address (info@, marketing@, noreply@ ...)
    not_relevant       outside every BU's ICP (company-level ICP verdict REJECT)
    unclear            nothing decides it -> stays as it is, a person can look

Rules decide first (vendor master, Vendor > Leads, known service domains,
party_relationships, billing customers, the role-mailbox rule, the existing
company ICP verdict). Only what the rules leave open goes up the ladder
(Qwen -> Haiku -> Sonnet) and a model label is accepted only when it quotes
the words it rests on from the record and, for "vendor", those words are
about selling sample/panel/data/services.
"""
import re
from typing import Any, Callable, Dict, Optional, Set

LABELS = ("potential_client", "client", "vendor", "role_mailbox", "not_relevant", "unclear")
MODEL_LABELS = ("potential_client", "vendor", "not_relevant", "unclear")
SCHEMA = {"type": "object", "required": ["label", "evidence"], "properties": {
    "label": {"type": "string", "enum": list(MODEL_LABELS)}, "evidence": {"type": "string"}}}
SYSTEM = ("We are a market research group: Survey Fieldwork (online sample and fieldwork for research agencies), "
          "Cogentix Research (research projects for brands and agencies) and BIM Wave (BIM/CAD services for "
          "architecture and construction). Decide what this company is to us. potential_client: it could buy "
          "research, sample, fieldwork or BIM services. vendor: it sells to us (online panels, sample providers, "
          "survey software, data tools, outsourced services). not_relevant: neither. unclear: the record does not "
          "say. evidence: copy the exact words from the record that decide it. JSON only.")
PANEL_VENDORS = {"cint", "dynata", "toluna", "lucid", "purespectrum", "prodege", "innovate mr", "innovatemr",
                 "samplecube", "marketcube", "repdata", "research desk", "pollfish", "qualtrics", "surveymonkey",
                 "netquest", "rakuten insight", "syno", "precision sample", "op4g", "zamplia", "borderless access",
                 "yuno", "tolunacorporate", "kantar profiles", "panelbase"}
VENDOR_WORDS = re.compile(r"\b(panel|panels|sample provider|sample supplier|online sample|respondents?|survey software|"
                          r"data (?:provider|platform|tool)|lead data|b2b data|outsourc\w*|staffing|software|saas|"
                          r"platform|agency (?:services|for hire)|freelanc\w*)\b", re.I)
MARKETING_LOCAL = re.compile(r"^(marketing|newsletter|news|promo|promotions|offers|campaigns?|events?|webinars?|"
                             r"hello|hi|team|community|updates?)([._-]|$)", re.I)


def _domain(rec: Dict[str, Any]) -> str:
    d = (rec.get("company_domain") or "").lower().strip()
    if not d and "@" in (rec.get("email") or ""):
        d = rec["email"].rsplit("@", 1)[1].lower()
    return re.sub(r"^www\.", "", d)


def rules(rec: Dict[str, Any], ctx: Dict[str, Set[str]]) -> Optional[Dict[str, str]]:
    """ctx: client_domains, vendor_domains, service_domains, client_emails, vendor_emails."""
    email = (rec.get("email") or "").lower()
    dom = _domain(rec)
    company = (rec.get("company_name") or rec.get("company") or "").lower()
    if email in ctx.get("client_emails", ()) or dom in ctx.get("client_domains", ()):
        return {"label": "client", "how": "party_relationships / billing customer"}
    if email in ctx.get("vendor_emails", ()) or dom in ctx.get("vendor_domains", ()):
        return {"label": "vendor", "how": "vendor master / Vendor > Leads / party_relationships"}
    if dom in ctx.get("service_domains", ()):
        return {"label": "vendor", "how": "known tool / service domain"}
    if email:
        try:
            from leads.system_addresses import rejection_reason
            if rejection_reason(email) in ("role_address", "system_address") or MARKETING_LOCAL.match(email.split("@")[0]):
                return {"label": "role_mailbox", "how": "shared / system / marketing address"}
        except Exception:
            if MARKETING_LOCAL.match(email.split("@")[0]):
                return {"label": "role_mailbox", "how": "marketing address"}
    if any(v in company for v in PANEL_VENDORS) or any(v.replace(" ", "") in dom for v in PANEL_VENDORS):
        return {"label": "vendor", "how": "known panel / sample company"}
    basket = (rec.get("outreach_bucket") or "").upper()
    # REJECT is not trusted on its own: it carries no reason and also covers
    # competitors excluded from outreach, which can still buy sample from SFW
    if basket in ("SFW", "COGENTIX_RESEARCH", "BIM"):
        return {"label": "potential_client", "how": f"company ICP verdict {basket}"}
    return None


def record_text(rec: Dict[str, Any]) -> str:
    parts = [f"Company: {rec.get('company_name') or rec.get('company') or ''}",
             f"Industry: {rec.get('company_industry') or rec.get('industry') or ''}",
             f"Website: {rec.get('company_website') or _domain(rec)}",
             f"Person's title: {rec.get('title') or ''}"]
    if rec.get("company_description"):
        parts.append(f"About: {rec['company_description'][:600]}")
    return "\n".join(p for p in parts if not p.endswith(": "))


def model_check(data: Any, clean: str) -> list:
    if not isinstance(data, dict) or data.get("label") not in MODEL_LABELS:
        return ["label not allowed"]
    ev = (data.get("evidence") or "").strip()
    if data["label"] != "unclear":
        if len(ev) < 3 or ev.lower() not in clean.lower():
            return ["evidence is not quoted from the record"]
        if data["label"] == "vendor" and not VENDOR_WORDS.search(ev):
            return ["vendor label without sell-side words in the evidence"]
    return []


def classify(rec: Dict[str, Any], ctx: Dict[str, Set[str]], model: Optional[Callable[..., Dict[str, Any]]] = None,
             ref: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    r = rules(rec, ctx)
    if r:
        return {**r, "tier": "rules"}
    if model is None:
        return {"label": "unclear", "how": "no rule; model not run", "tier": None}
    out = model(task="contact_classification", system=SYSTEM, body=record_text(rec), schema=SCHEMA,
                code_check=model_check, ref=ref, enqueue_on_fail=False)
    if out.get("status") == "deferred":
        return {"label": None, "how": "deferred to the night window", "tier": None}
    d = out.get("data") if isinstance(out.get("data"), dict) else None
    if d and not out.get("problems"):
        return {"label": d["label"], "how": f"model: {d.get('evidence', '')[:120]}", "tier": out.get("tier")}
    return {"label": "unclear", "how": "no tier produced a grounded answer", "tier": None}
