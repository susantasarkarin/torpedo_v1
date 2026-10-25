"""Signal + rule layer (MARKETING_PLAN 4.1.1-4.1.2, 4.2). Code computes; every candidate carries
the numbers behind it (evidence), a code estimate of its INR impact (for D14 ranking) and the
metric its outcome will be measured on.

Rules read what the integrations write (ad_metrics_daily, search_terms, ads, audiences,
gsc_pages_daily, seo_issues, touchpoints, web_visitors, web_events, experiments,
content_items, social_posts). A table that is still empty yields no candidates.
Thresholds live in config section "marketing" -> "rules" (defaults below).
"""
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from marketing import schema

RULES = {
    "pause_min_spend_inr": 15000, "pause_cpl_multiple": 2.0, "zero_rfq_days": 30,
    "realloc_step_pct": 10, "bid_cpa_over_pct": 20, "bid_step_pct": 10, "bid_min_conversions": 15,
    "negative_min_spend_inr": 1500, "negative_min_clicks": 10,
    "ctr_min_impressions": 1000, "fatigue_frequency": 4.0, "audience_cpl_multiple": 2.0,
    "seo_min_impressions": 200, "seo_pos_band": [8, 20], "seo_low_ctr_pos": 8, "seo_low_ctr": 0.02,
    "lead_hot_score": 60, "nba_quiet_days": 7, "test_alpha": 0.05, "test_min_per_arm": 200, "test_max_days": 42,
    "spend_spike_multiple": 2.0, "ctr_crash_drop": 0.5, "form_drop_pct": 0.6, "max_per_run": 10,
    "target_cpl_inr": {}, "target_cost_per_rfq_inr": {},           # per BU, owner (M-CP2)
    "assumed_rfq_value_inr": 150000,                                 # D7/D10 impact estimate until won data exists
}


def _test_host(url: Optional[str]) -> bool:
    import ipaddress
    from urllib.parse import urlparse
    h = (urlparse(url or "").hostname or "").lower()
    if h in ("localhost",) or h.endswith((".local", ".test")):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return ip.is_loopback or ip.is_private
    except ValueError:
        return False


def _ymd(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def two_proportion(a_conv: int, a_n: int, b_conv: int, b_n: int) -> Dict[str, float]:
    """Two-sided two-proportion z-test (D12, D5). Code only; Qwen just explains the result."""
    if min(a_n, b_n) <= 0:
        return {"z": 0.0, "p": 1.0, "a_rate": 0.0, "b_rate": 0.0}
    pa, pb = a_conv / a_n, b_conv / b_n
    p = (a_conv + b_conv) / (a_n + b_n)
    se = math.sqrt(p * (1 - p) * (1 / a_n + 1 / b_n)) or 1e-12
    z = (pb - pa) / se
    pval = math.erfc(abs(z) / math.sqrt(2))
    return {"z": round(z, 3), "p": round(pval, 4), "a_rate": round(pa, 5), "b_rate": round(pb, 5)}


def _sum_by(rows: List[Dict[str, Any]], key: str) -> Dict[Any, Dict[str, float]]:
    out: Dict[Any, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        k = r.get(key)
        for f in ("spend_inr", "impressions", "clicks", "conversions", "leads", "rfqs", "won_inr"):
            out[k][f] += float(r.get(f) or 0)
        out[k]["_bu"], out[k]["_platform"] = r.get("bu"), r.get("platform")
        out[k]["_name"] = r.get("name") or out[k].get("_name")
    return out


def cand(t, entity_key, action, *, bu=None, platform=None, label=None, params=None, evidence=None, targets=None,
         rule_id="", impact_inr=0.0, metric=None, min_volume=20) -> Dict[str, Any]:
    return {"decision_type": t, "entity_key": entity_key, "entity_label": label or entity_key, "bu": bu, "platform": platform,
            "action": action, "parameters": params or {}, "evidence": evidence or {}, "targets": targets or {},
            "rule_id": rule_id, "impact_inr": round(float(impact_inr), 2), "metric": metric or {}, "min_volume": min_volume}


# ------------------------------------------------------------------ paid media D1-D6
def paid_candidates(ea, now: datetime, R: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    since30 = _ymd(now - timedelta(days=R["zero_rfq_days"]))
    rows = list(ea["ad_metrics_daily"].find({"level": "campaign", "date": {"$gte": since30}}))
    camps = _sum_by(rows, "entity_id")
    tcpl = R.get("target_cpl_inr") or {}
    # D2 pause / cut: spend, 0 RFQs in 30 d, CPL > 2x target
    for cid, m in camps.items():
        bu, plat, tgt = m["_bu"], m["_platform"], (tcpl.get(m["_bu"]) if isinstance(tcpl, dict) else None)
        cpl = m["spend_inr"] / m["leads"] if m["leads"] else None
        if m["spend_inr"] >= R["pause_min_spend_inr"] and m["rfqs"] == 0 and \
                (cpl is None or (tgt and cpl > R["pause_cpl_multiple"] * tgt)):
            out.append(cand("D2", f"{plat}:campaign:{cid}", "pause", bu=bu, platform=plat, label=m.get("_name"),
                            evidence={"spend_inr_30d": round(m["spend_inr"]), "leads_30d": m["leads"], "rfqs_30d": 0,
                                      "cpl_inr": round(cpl) if cpl else None, "target_cpl_inr": tgt,
                                      "conversions": m["conversions"], "spend_inr": m["spend_inr"], "clicks": m["clicks"]},
                            rule_id="d2_spend_no_rfq", impact_inr=m["spend_inr"],
                            metric={"name": "wasted_spend_inr", "entity": cid, "higher_is_better": False}))
    # D1 shift budget: within BU + platform, worst cost per RFQ -> best
    groups: Dict[tuple, List] = defaultdict(list)
    for cid, m in camps.items():
        groups[(m["_bu"], m["_platform"])].append((cid, m))
    for (bu, plat), cs in groups.items():
        scored = [(cid, m, m["spend_inr"] / m["rfqs"]) for cid, m in cs if m["rfqs"] > 0]
        if len(scored) < 2:
            continue
        scored.sort(key=lambda x: x[2])
        best, worst = scored[0], scored[-1]
        if worst[2] > 1.5 * best[2]:
            out.append(cand("D1", f"{plat}:{bu}:realloc", "shift_budget", bu=bu, platform=plat,
                            label=f"{bu} {plat}: {worst[1].get('_name') or worst[0]} -> {best[1].get('_name') or best[0]}",
                            params={"from": worst[0], "to": best[0], "shift_pct": R["realloc_step_pct"], "net_change_inr": 0},
                            evidence={"from_cost_per_rfq_inr": round(worst[2]), "to_cost_per_rfq_inr": round(best[2]),
                                      "from_spend_inr_30d": round(worst[1]["spend_inr"]),
                                      "conversions": sum(m["conversions"] for _, m, _ in scored)},
                            rule_id="d1_cost_per_rfq_gap",
                            impact_inr=worst[1]["spend_inr"] * R["realloc_step_pct"] / 100 * (1 - best[2] / worst[2]),
                            metric={"name": "cost_per_rfq_inr", "entity": f"{bu}:{plat}", "higher_is_better": False}))
    # D3 bids / targets: CPA above target with enough conversions
    for cid, m in camps.items():
        tgt = (tcpl.get(m["_bu"]) if isinstance(tcpl, dict) else None)
        if tgt and m["conversions"] >= R["bid_min_conversions"]:
            cpa = m["spend_inr"] / m["conversions"]
            if cpa > tgt * (1 + R["bid_cpa_over_pct"] / 100):
                out.append(cand("D3", f"{m['_platform']}:campaign:{cid}", "adjust_target", bu=m["_bu"], platform=m["_platform"],
                                label=m.get("_name"), params={"change_pct": -R["bid_step_pct"]},
                                evidence={"cpa_inr": round(cpa), "target_cpa_inr": tgt, "conversions": m["conversions"]},
                                rule_id="d3_cpa_over_target", impact_inr=(cpa - tgt) * m["conversions"] * 0.25,
                                metric={"name": "cpa_inr", "entity": cid, "higher_is_better": False}))
    # D4 negative keywords: search terms with spend and no leads, one batched candidate per campaign
    st = list(ea["search_terms"].find({"date": {"$gte": since30}}))
    by_camp: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    meta: Dict[str, Dict[str, Any]] = {}
    for r in st:
        t = by_camp[r["campaign_id"]][r["term"]]
        for f in ("spend_inr", "clicks", "leads"):
            t[f] += float(r.get(f) or 0)
        meta[r["campaign_id"]] = {"bu": r.get("bu"), "platform": r.get("platform") or "google"}
    for cid, terms in by_camp.items():
        waste = [(term, v) for term, v in terms.items() if v["leads"] == 0
                 and (v["spend_inr"] >= R["negative_min_spend_inr"] or v["clicks"] >= R["negative_min_clicks"])]
        if waste:
            waste.sort(key=lambda x: -x[1]["spend_inr"])
            top = waste[:20]
            out.append(cand("D4", f"google:campaign:{cid}:negatives", "add_negatives", bu=meta[cid]["bu"], platform="google",
                            params={"terms": [t for t, _ in top], "match_type": "phrase"},
                            evidence={"terms": len(top), "wasted_spend_inr_30d": round(sum(v["spend_inr"] for _, v in top)),
                                      "clicks": sum(v["clicks"] for _, v in top),
                                      "top": {t: round(v["spend_inr"]) for t, v in top[:5]}},
                            rule_id="d4_spend_no_leads", impact_inr=sum(v["spend_inr"] for _, v in top),
                            metric={"name": "wasted_spend_inr", "entity": cid, "higher_is_better": False}))
    # D5 creative: CTR winner by z-test inside an ad group; fatigue by frequency
    ads = list(ea["ad_metrics_daily"].find({"level": "ad", "date": {"$gte": _ymd(now - timedelta(days=14))}}))
    grp: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    info: Dict[str, Dict[str, Any]] = {}
    for r in ads:
        a = grp[r.get("group_id") or r.get("campaign_id")][r["entity_id"]]
        for f in ("impressions", "clicks", "conversions", "spend_inr"):
            a[f] += float(r.get(f) or 0)
        a["frequency"] = max(a["frequency"], float(r.get("frequency") or 0))
        info[r["entity_id"]] = {"bu": r.get("bu"), "platform": r.get("platform")}
    for gid, arms in grp.items():
        ok = [(aid, v) for aid, v in arms.items() if v["impressions"] >= R["ctr_min_impressions"]]
        if len(ok) >= 2:
            ok.sort(key=lambda x: x[1]["clicks"] / x[1]["impressions"])
            lo, hi = ok[0], ok[-1]
            t = two_proportion(int(lo[1]["clicks"]), int(lo[1]["impressions"]), int(hi[1]["clicks"]), int(hi[1]["impressions"]))
            if t["p"] < R["test_alpha"]:
                out.append(cand("D5", f"{info[hi[0]]['platform']}:adgroup:{gid}", "promote_winner", bu=info[hi[0]]["bu"],
                                platform=info[hi[0]]["platform"], params={"winner": hi[0], "loser": lo[0]},
                                evidence={"winner_ctr": t["b_rate"], "loser_ctr": t["a_rate"], "p_value": t["p"],
                                          "clicks": hi[1]["clicks"] + lo[1]["clicks"]},
                                rule_id="d5_ctr_winner", impact_inr=lo[1]["spend_inr"] * 0.2,
                                metric={"name": "ctr", "entity": gid, "higher_is_better": True}))
        for aid, v in arms.items():
            if v["frequency"] >= R["fatigue_frequency"]:
                out.append(cand("D5", f"{info[aid]['platform']}:ad:{aid}", "request_variants", bu=info[aid]["bu"],
                                platform=info[aid]["platform"], evidence={"frequency": v["frequency"], "clicks": v["clicks"]},
                                rule_id="d5_fatigue", impact_inr=v["spend_inr"] * 0.1,
                                metric={"name": "ctr", "entity": aid, "higher_is_better": True}))
    # D6 audience: CPL > 2x the platform average
    aud = list(ea["ad_metrics_daily"].find({"level": "audience", "date": {"$gte": since30}}))
    am = _sum_by(aud, "entity_id")
    tot = defaultdict(lambda: [0.0, 0.0])
    for m in am.values():
        tot[(m["_bu"], m["_platform"])][0] += m["spend_inr"]
        tot[(m["_bu"], m["_platform"])][1] += m["leads"]
    for aid, m in am.items():
        s, l = tot[(m["_bu"], m["_platform"])]
        avg = s / l if l else None
        cpl = m["spend_inr"] / m["leads"] if m["leads"] else None
        if avg and m["spend_inr"] >= R["negative_min_spend_inr"] and (cpl is None or cpl > R["audience_cpl_multiple"] * avg):
            out.append(cand("D6", f"{m['_platform']}:audience:{aid}", "exclude_audience", bu=m["_bu"], platform=m["_platform"],
                            label=m.get("_name"), evidence={"audience_cpl_inr": round(cpl) if cpl else None,
                                                            "platform_avg_cpl_inr": round(avg), "spend_inr": round(m["spend_inr"]),
                                                            "leads": m["leads"]},
                            rule_id="d6_audience_cpl", impact_inr=m["spend_inr"] * 0.5,
                            metric={"name": "cpl_inr", "entity": f"{m['_bu']}:{m['_platform']}", "higher_is_better": False}))
    return out


# ------------------------------------------------------------------ SEO + content D7-D9
def seo_candidates(ea, now: datetime, R: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    since = _ymd(now - timedelta(days=28))
    pages = _sum_by([dict(r, spend_inr=0, leads=0, rfqs=0, won_inr=0, conversions=0, platform="gsc",
                          entity=f"{r['site']}|{r['page']}") for r in ea["gsc_pages_daily"].find({"date": {"$gte": since}})], "entity")
    pos: Dict[str, List[float]] = defaultdict(list)
    for r in ea["gsc_pages_daily"].find({"date": {"$gte": since}}):
        pos[f"{r['site']}|{r['page']}"].append(float(r.get("position") or 0))
    lo, hi = R["seo_pos_band"]
    opp = []
    for k, m in pages.items():
        p = sum(pos[k]) / len(pos[k]) if pos[k] else 0
        ctr = m["clicks"] / m["impressions"] if m["impressions"] else 0
        if m["impressions"] >= R["seo_min_impressions"] and (lo <= p <= hi or (p < R["seo_low_ctr_pos"] and ctr < R["seo_low_ctr"])):
            opp.append({"page": k.split("|", 1)[1], "site": k.split("|", 1)[0], "impressions": int(m["impressions"]),
                        "clicks": int(m["clicks"]), "position": round(p, 1), "ctr": round(ctr, 4), "bu": m["_bu"]})
    issues = list(ea["seo_issues"].find({"status": "open", "severity": {"$in": ["critical", "high", "medium"]}}))
    sites = sorted({o["site"] for o in opp} | {i["site"] for i in issues})
    for site in sites:
        so = sorted([o for o in opp if o["site"] == site], key=lambda o: -o["impressions"])[:10]
        si = [i for i in issues if i["site"] == site]
        sev = defaultdict(int)
        for i in si:
            sev[i["severity"]] += 1
        bu = (so[0]["bu"] if so else None) or (si[0].get("bu") if si else None)
        # impact: extra clicks if the opportunities reach page 1 at ~5% CTR, valued at a share of an RFQ
        extra = sum(max(0, 0.05 * o["impressions"] - o["clicks"]) for o in so)
        out.append(cand("D7", f"seo:{site}", "rank_fixes", bu=bu, platform="site", label=site,
                        params={"opportunities": [o["page"] for o in so], "issue_codes": sorted({i["code"] for i in si})[:15]},
                        evidence={"opportunity_pages": len(so), "impressions_28d": sum(o["impressions"] for o in so),
                                  "clicks_28d": sum(o["clicks"] for o in so), "open_issues": len(si),
                                  "high_issues": sev["high"] + sev["critical"], "medium_issues": sev["medium"],
                                  "clicks": sum(o["clicks"] for o in so)},
                        rule_id="d7_gsc_opportunity_plus_audit",
                        impact_inr=extra * 0.01 * R["assumed_rfq_value_inr"] * 0.1 + 500 * (sev["high"] + sev["critical"]),
                        metric={"name": "organic_clicks", "entity": site, "higher_is_better": True}, min_volume=5))
    return out


def content_candidates(ea, now: datetime, R: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    posts = list(ea["social_posts"].find({"published_at": {"$gte": now - timedelta(days=90)}}))
    by_bu = defaultdict(list)
    for p in posts:
        by_bu[(p.get("bu"), p.get("platform"))].append(p)
    for (bu, plat), ps in by_bu.items():
        if len(ps) < 8:
            continue
        slots = defaultdict(lambda: [0.0, 0])
        for p in ps:
            at = p["published_at"] + timedelta(hours=5, minutes=30)                 # IST slot
            k = f"{at.strftime('%a')} {at.hour:02d}:00"
            slots[k][0] += float(p.get("engagement_rate") or 0)
            slots[k][1] += 1
        ranked = sorted(((k, v[0] / v[1], v[1]) for k, v in slots.items() if v[1] >= 2), key=lambda x: -x[1])
        if ranked:
            out.append(cand("D9", f"{plat}:{bu}:schedule", "set_schedule", bu=bu, platform=plat,
                            params={"slots": [k for k, _, _ in ranked[:3]], "per_week": min(5, max(2, len(ps) // 13))},
                            evidence={"posts_90d": len(ps), "best_slot_engagement": round(ranked[0][1], 4),
                                      "avg_engagement": round(sum(float(p.get("engagement_rate") or 0) for p in ps) / len(ps), 4),
                                      "clicks": sum(float(p.get("clicks") or 0) for p in ps)},
                            rule_id="d9_engagement_by_slot", impact_inr=0,
                            metric={"name": "engagement_rate", "entity": f"{bu}:{plat}", "higher_is_better": True}, min_volume=8))
    gaps = list(ea["content_gaps"].find({"status": {"$in": ["open", None]}}))
    for bu in sorted({g.get("bu") for g in gaps if g.get("bu")}):
        mine = [g for g in gaps if g.get("bu") == bu][:8]
        out.append(cand("D8", f"content:{bu}:plan", "plan_topics", bu=bu, platform="content",
                        params={"topics": [g.get("topic") or g.get("query") for g in mine]},
                        evidence={"open_gaps": len(mine), "clicks": 0}, rule_id="d8_content_gaps", impact_inr=0,
                        metric={"name": "content_leads", "entity": bu, "higher_is_better": True}, min_volume=1))
    return out


# ------------------------------------------------------------------ leads D10-D11
def lead_candidates(ea, crm, now: datetime, R: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Leads with recent web / form activity only (a few a day), never the whole table."""
    out = []
    since = now - timedelta(days=14)
    active = defaultdict(list)
    for t in ea["touchpoints"].find({"at": {"$gte": since}, "kind": {"$in": ["visit", "form", "mail_in", "lead_form", "chat"]}}):
        if _test_host(t.get("landing")):          # staging / local test submissions are not people
            continue
        active[t["lead_id"]].append(t)
    # a pending website-enquiry item already carries the 1-hour reply (6.3): no second item for the same person
    in_inbound = {str((i.get("payload") or {}).get("lead_id")) for i in
                  ea["review_queue_items"].find({"type": "inbound_lead", "status": "pending"})}
    for lid, tps in list(active.items())[:200]:
        if lid in in_inbound:
            continue
        score, why = 0, []
        kinds = {t["kind"] for t in tps}
        if "form" in kinds or "lead_form" in kinds:
            score += 40; why.append("form")
        if "mail_in" in kinds:
            score += 25; why.append("replied")
        visits = [t for t in tps if t["kind"] == "visit"]
        if len(visits) >= 2:
            score += 20; why.append(f"{len(visits)} visits")
        if any(any(p in (t.get("landing") or "") for p in ("/pricing", "/panel", "/rate", "/contact")) for t in visits):
            score += 15; why.append("high-intent page")
        if any(t.get("channel") in ("paid_search", "paid_social") for t in tps):
            score += 5; why.append("paid click")
        grade = "A" if score >= 70 else "B" if score >= R["lead_hot_score"] else "C" if score >= 30 else "D"
        bu = next((t.get("bu") for t in tps if t.get("bu")), None)
        last = max(t["at"] for t in tps)
        opted_wa = bool(ea["whatsapp_optins"].find_one({"lead_id": lid, "granted": True}))
        route = ("route_sales_call" if grade == "A" else "route_whatsapp" if grade == "B" and opted_wa
                 else "route_sequence" if grade in ("B", "C") else "route_nurture")
        out.append(cand("D10", f"lead:{lid}", route, bu=bu, platform="crm", params={"grade": grade, "score": score},
                        evidence={"score": score, "signals": why, "touches_14d": len(tps), "whatsapp_optin": opted_wa,
                                  "clicks": len(tps) * 10},
                        rule_id="d10_touch_score", impact_inr=R["assumed_rfq_value_inr"] * score / 1000,
                        metric={"name": "lead_to_rfq", "entity": lid, "higher_is_better": True}, min_volume=3))
        quiet = (now - last).days
        if grade in ("A", "B") and quiet >= R["nba_quiet_days"]:
            out.append(cand("D11", f"lead:{lid}:nba", "next_touch", bu=bu, platform="crm",
                            params={"channel": "whatsapp" if opted_wa else "email", "message_type": "follow_up",
                                    "when": "next_working_morning"},
                            evidence={"days_since_last_touch": quiet, "grade": grade, "score": score, "clicks": len(tps) * 10},
                            rule_id="d11_quiet_hot_lead", impact_inr=R["assumed_rfq_value_inr"] * 0.02,
                            metric={"name": "lead_reply", "entity": lid, "higher_is_better": True}, min_volume=3))
    return out


# ------------------------------------------------------------------ experiments D12, anomalies D13
def experiment_candidates(ea, now: datetime, R: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for x in ea["experiments"].find({"status": "running"}):
        arms = x.get("arms") or []
        if len(arms) != 2:
            continue
        a, b = arms
        t = two_proportion(int(a.get("conversions") or 0), int(a.get("n") or 0), int(b.get("conversions") or 0), int(b.get("n") or 0))
        enough = min(int(a.get("n") or 0), int(b.get("n") or 0)) >= max(R["test_min_per_arm"], int(x.get("min_per_arm") or 0))
        age = (now - x.get("started_at", now)).days
        ev = {"a_rate": t["a_rate"], "b_rate": t["b_rate"], "p_value": t["p"], "a_n": a.get("n"), "b_n": b.get("n"),
              "days_running": age, "clicks": (a.get("n") or 0) + (b.get("n") or 0)}
        if enough and t["p"] < R["test_alpha"]:
            win = b if t["b_rate"] > t["a_rate"] else a
            out.append(cand("D12", f"experiment:{x['_id']}", "declare_winner", bu=x.get("bu"), platform=x.get("platform"),
                            label=x.get("name"), params={"winner": win.get("name")}, evidence=ev, rule_id="d12_significant",
                            metric={"name": x.get("metric") or "conversion_rate", "entity": str(x["_id"]), "higher_is_better": True}))
        elif age >= R["test_max_days"]:
            out.append(cand("D12", f"experiment:{x['_id']}", "stop_test", bu=x.get("bu"), platform=x.get("platform"),
                            label=x.get("name"), evidence=ev, rule_id="d12_max_duration",
                            metric={"name": x.get("metric") or "conversion_rate", "entity": str(x["_id"]), "higher_is_better": True}))
    return out


def anomaly_candidates(ea, now: datetime, R: Dict[str, Any], sites: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    day = _ymd(now - timedelta(days=1))
    week = [_ymd(now - timedelta(days=i)) for i in range(2, 9)]
    rows = list(ea["ad_metrics_daily"].find({"level": "campaign", "date": {"$in": [day] + week}}))
    per = defaultdict(lambda: {"y": defaultdict(float), "w": defaultdict(float), "bu": None, "platform": None, "name": None})
    for r in rows:
        p = per[r["entity_id"]]
        tgt = p["y"] if r["date"] == day else p["w"]
        for f in ("spend_inr", "impressions", "clicks"):
            tgt[f] += float(r.get(f) or 0)
        p["bu"], p["platform"], p["name"] = r.get("bu"), r.get("platform"), r.get("name")
    for cid, p in per.items():
        avg = p["w"]["spend_inr"] / 7
        if avg and p["y"]["spend_inr"] > R["spend_spike_multiple"] * avg:
            out.append(cand("D13", f"{p['platform']}:campaign:{cid}:spike", "pause_spend_spike", bu=p["bu"], platform=p["platform"],
                            label=p["name"], evidence={"spend_yesterday_inr": round(p["y"]["spend_inr"]), "avg_daily_7d_inr": round(avg),
                                                       "conversions": 0, "spend_inr": p["y"]["spend_inr"], "clicks": p["y"]["clicks"]},
                            rule_id="d13_spend_spike", impact_inr=p["y"]["spend_inr"] - avg,
                            metric={"name": "daily_spend_inr", "entity": cid, "higher_is_better": False}, min_volume=1))
        wctr = p["w"]["clicks"] / p["w"]["impressions"] if p["w"]["impressions"] else 0
        yctr = p["y"]["clicks"] / p["y"]["impressions"] if p["y"]["impressions"] > 500 else None
        if wctr and yctr is not None and yctr < wctr * (1 - R["ctr_crash_drop"]):
            out.append(cand("D13", f"{p['platform']}:campaign:{cid}:ctr", "alert", bu=p["bu"], platform=p["platform"], label=p["name"],
                            evidence={"ctr_yesterday": round(yctr, 4), "ctr_7d": round(wctr, 4), "clicks": p["y"]["clicks"]},
                            rule_id="d13_ctr_crash", metric={"name": "ctr", "entity": cid, "higher_is_better": True}, min_volume=1))
    for s in sites:
        last = ea["web_events"].find_one({"host": s["domain"]}, sort=[("at", -1)])
        if last and now - last["at"] > timedelta(hours=24):
            out.append(cand("D13", f"site:{s['domain']}:silent", "open_incident", bu=s.get("bu"), platform="site", label=s["domain"],
                            evidence={"hours_silent": int((now - last["at"]).total_seconds() // 3600), "clicks": 0},
                            rule_id="d13_tracker_silent", metric={"name": "tracker_events", "entity": s["domain"], "higher_is_better": True},
                            min_volume=1))
        y = ea["web_events"].count_documents({"host": s["domain"], "type": "form_submit", "at": {"$gte": now - timedelta(days=1)}})
        w = ea["web_events"].count_documents({"host": s["domain"], "type": "form_submit",
                                              "at": {"$gte": now - timedelta(days=8), "$lt": now - timedelta(days=1)}}) / 7
        if w >= 1 and y < w * (1 - R["form_drop_pct"]):
            out.append(cand("D13", f"site:{s['domain']}:forms", "alert", bu=s.get("bu"), platform="site", label=s["domain"],
                            evidence={"form_submits_24h": y, "avg_daily_7d": round(w, 2), "clicks": 0},
                            rule_id="d13_conversion_drop", metric={"name": "form_submits", "entity": s["domain"], "higher_is_better": True},
                            min_volume=1))
    return out


# ------------------------------------------------------------------ D14 weekly review (ranked in code)
def weekly_candidate(open_cands: List[Dict[str, Any]], now: datetime) -> Optional[Dict[str, Any]]:
    ranked = sorted((c for c in open_cands if c["decision_type"] != "D14"), key=lambda c: -c.get("impact_inr", 0))[:5]
    if not ranked:
        return None
    return cand("D14", f"weekly:{now:%G-W%V}", "weekly_actions", platform="all",
                params={"actions": [{"type": c["decision_type"], "entity": c["entity_label"], "action": c["action"],
                                     "impact_inr": c["impact_inr"]} for c in ranked]},
                evidence={"candidates": len(open_cands), "top5_impact_inr": round(sum(c["impact_inr"] for c in ranked)),
                          "clicks": 0}, rule_id="d14_rank_by_impact", impact_inr=sum(c["impact_inr"] for c in ranked),
                metric={"name": "weekly_review", "entity": f"{now:%G-W%V}", "higher_is_better": True}, min_volume=1)


LANE_TYPES = {"P1": {"D13"}, "P2": {"D2", "D4", "D10", "D11"}, "P3": {"D1", "D3", "D5", "D6", "D7", "D8", "D9", "D12", "D14"}}


def candidates(gd: Callable, now: datetime, R: Dict[str, Any], sites: List[Dict[str, Any]], types: Optional[set] = None) -> List[Dict[str, Any]]:
    ea, crm = gd(schema.DB), gd("crm_db")
    want = types or set().union(*LANE_TYPES.values())
    out: List[Dict[str, Any]] = []
    if want & {"D1", "D2", "D3", "D4", "D5", "D6"}:
        out += paid_candidates(ea, now, R)
    if "D7" in want:
        out += seo_candidates(ea, now, R)
    if want & {"D8", "D9"}:
        out += content_candidates(ea, now, R)
    if want & {"D10", "D11"}:
        out += lead_candidates(ea, crm, now, R)
    if "D12" in want:
        out += experiment_candidates(ea, now, R)
    if "D13" in want:
        out += anomaly_candidates(ea, now, R, sites)
    out = [c for c in out if c["decision_type"] in want]
    if "D14" in want:
        w = weekly_candidate(out, now)
        if w:
            out.append(w)
    return out


def run(lane: str, gd: Optional[Callable] = None, *, now: Optional[datetime] = None, qwen=None,
        dry_run: bool = False) -> Dict[str, Any]:
    """One lane: build candidates (code) -> engine.decide each (bounded per run, highest impact first)."""
    if gd is None:
        from database import get_database as gd
    from marketing import engine
    from platform_core import config_store
    now = now or datetime.utcnow()
    mc = config_store.get("marketing")
    R = {**RULES, **(mc.get("rules") or {})}
    sites = config_store.get("web").get("sites") or []
    types = LANE_TYPES[lane]
    if lane == "P3" and now.weekday() != 0:          # weekly review on Mondays only
        types = types - {"D14"}
    cs = sorted(candidates(gd, now, R, sites, types), key=lambda c: -c.get("impact_inr", 0))
    rep = {"lane": lane, "candidates": len(cs), "by_type": {}, "decisions": {}}
    for c in cs:
        rep["by_type"][c["decision_type"]] = rep["by_type"].get(c["decision_type"], 0) + 1
    if dry_run:
        rep["sample"] = [{k: c[k] for k in ("decision_type", "entity_label", "action", "impact_inr", "evidence")} for c in cs[:5]]
        return rep
    gd(schema.DB)["decision_candidates"].insert_many(
        [schema.stamp({**c, "status": "new", "lane": lane}, bu=c["bu"] if c.get("bu") in schema.BUS else None,
                      source="rule_layer", now=now) for c in cs]) if cs else None
    for c in cs[:int(R["max_per_run"])]:
        d = engine.decide(c, gd=gd, qwen=qwen, cfg=mc, now=now)
        rep["decisions"][d["status"]] = rep["decisions"].get(d["status"], 0) + 1
    return rep


# ------------------------------------------------------------------ outcome metrics (4.1.7)
def outcome_metric(gd: Callable) -> Callable[[Dict[str, Any]], Optional[Dict[str, float]]]:
    """metric(decision) for engine.measure_due: the same window before vs after execution."""
    ea = gd(schema.DB)

    def ads(entity, since, until, level="campaign"):
        q = {"date": {"$gte": _ymd(since), "$lt": _ymd(until)}, "level": level}
        rows = [r for r in ea["ad_metrics_daily"].find(q) if entity in (r.get("entity_id"), r.get("campaign_id"), r.get("group_id"),
                                                                        f"{r.get('bu')}:{r.get('platform')}")]
        return {f: sum(float(r.get(f) or 0) for r in rows) for f in ("spend_inr", "clicks", "impressions", "conversions", "leads", "rfqs")}

    def value(name, entity, since, until):
        if name in ("wasted_spend_inr", "daily_spend_inr", "cpa_inr", "cpl_inr", "cost_per_rfq_inr", "ctr"):
            a = ads(entity, since, until, "ad" if name == "ctr" and ":" not in entity else "campaign")
            if name == "wasted_spend_inr":
                st = [r for r in ea["search_terms"].find({"campaign_id": entity, "date": {"$gte": _ymd(since), "$lt": _ymd(until)}})]
                return sum(float(r.get("spend_inr") or 0) for r in st if not r.get("leads")) if st else (a["spend_inr"] if not a["rfqs"] else 0)
            if name == "daily_spend_inr":
                return a["spend_inr"] / max(1, (until - since).days)
            if name == "ctr":
                return a["clicks"] / a["impressions"] if a["impressions"] else None
            den = {"cpa_inr": a["conversions"], "cpl_inr": a["leads"], "cost_per_rfq_inr": a["rfqs"]}[name]
            return a["spend_inr"] / den if den else None
        if name == "organic_clicks":
            return sum(float(r.get("clicks") or 0) for r in ea["gsc_pages_daily"].find(
                {"site": {"$in": [entity, f"sc-domain:{entity}", f"https://{entity}/"]}, "date": {"$gte": _ymd(since), "$lt": _ymd(until)}}))
        if name in ("form_submits", "tracker_events"):
            q = {"host": entity, "at": {"$gte": since, "$lt": until}}
            if name == "form_submits":
                q["type"] = "form_submit"
            return ea["web_events"].count_documents(q)
        if name in ("lead_reply", "lead_to_rfq"):
            kind = "mail_in" if name == "lead_reply" else None
            q = {"lead_id": entity, "at": {"$gte": since, "$lt": until}}
            if kind:
                q["kind"] = kind
            return float(ea["touchpoints"].count_documents(q))
        return None

    def metric(d: Dict[str, Any]) -> Optional[Dict[str, float]]:
        m = d.get("metric") or {}
        if not m.get("name") or not d.get("executed_at"):
            return None
        win = d["outcome_due_at"] - d["executed_at"]
        b = value(m["name"], m.get("entity"), d["executed_at"] - win, d["executed_at"])
        a = value(m["name"], m.get("entity"), d["executed_at"], d["outcome_due_at"])
        if a is None or b is None:
            return None
        return {"baseline": round(b, 4), "actual": round(a, 4), "higher_is_better": m.get("higher_is_better", True), "name": m["name"]}
    return metric
