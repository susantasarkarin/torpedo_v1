"""Set business_context on SFW and Cogentix campaigns, then launch them."""
import urllib.request, json

BASE = "http://localhost:8000/api/cold-outreach"

sfw_ctx = {
    "description": "Torpedo Research Survey Fieldwork delivers end-to-end quantitative data collection for market research agencies globally. We operate a proprietary online panel of 2M+ respondents across 40+ countries specialising in hard-to-reach B2B and consumer segments.",
    "value_proposition": "We complete what others quote and decline. With a 97% on-time completion rate and a dedicated PM per study, we eliminate fieldwork anxiety. Our niche B2B panel gives access to the segments your current suppliers cannot reach at competitive CPIs without sacrificing quality.",
    "target_customer": "Market research agencies and boutique research firms; panel companies looking for supplemental sample; corporate insights teams running quantitative studies; research operations leads managing vendor relationships",
    "tone": "professional",
    "sender_name": "Indira Das",
    "sender_title": "Director of Business Development, Torpedo Research",
}

cgx_ctx = {
    "description": "Cogentix Research is our brand intelligence and consumer insights arm, delivering custom qualitative and quantitative research for FMCG, retail, pharma, media, and financial services companies. We translate raw data into executive-ready strategic intelligence.",
    "value_proposition": "We are an insight partner not a data vendor. Our researchers have worked inside brand teams they now advise. Every deliverable comes with a so-what layer: commercially grounded recommendations written for the boardroom.",
    "target_customer": "Insights and consumer intelligence managers at FMCG/CPG; brand strategy directors at marketing agencies; market research managers at pharma and healthcare; customer experience leads at banks and fintech",
    "tone": "professional",
    "sender_name": "Meera Rathi",
    "sender_title": "Director of Client Solutions, Cogentix Research",
}

campaigns = [
    ("2a451219-3ce3-43fe-91d3-e1a3155f5363", sfw_ctx, "SFW"),
    ("a981bdcd-fbd5-497a-8522-e886e9c2f57c", cgx_ctx, "Cogentix"),
]

for campaign_id, ctx, label in campaigns:
    # Set context
    body = json.dumps(ctx).encode()
    req = urllib.request.Request(
        f"{BASE}/campaigns/{campaign_id}/context",
        data=body,
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        print(f"[{label}] context set: {resp.status} {resp.read().decode()[:60]}")
    except Exception as e:
        print(f"[{label}] context FAILED: {e}")

    # Launch campaign
    req2 = urllib.request.Request(
        f"{BASE}/campaigns/{campaign_id}/launch",
        data=b"",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        resp2 = urllib.request.urlopen(req2, timeout=15)
        print(f"[{label}] LAUNCHED: {resp2.status} {resp2.read().decode()[:120]}")
    except Exception as e:
        print(f"[{label}] launch FAILED: {e}")
