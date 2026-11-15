"""
Lead-gen guards found live 2026-09-27/28: search stopped for a full day after
our own hourly cap refused one query, and web-search leads got addresses built
on the platform that listed them (…@uk.linkedin.com, …@www.nvidia.com).
"""
from datetime import datetime

from leads.email_pattern_system import company_email_domain, render_pattern_email
from leads.ingestion import cse_resume_time


# ---- Google CSE stops end when their limit resets ------------------------------

def test_hourly_cap_stops_search_until_the_next_hour_not_a_day():
    now = datetime(2026, 9, 27, 18, 53, 13)
    assert cse_resume_time("Hourly quota exceeded (50/hour). Resets within the hour.", now) == \
        datetime(2026, 9, 27, 19, 0, 0)


def test_monthly_budget_stops_search_until_next_month():
    now = datetime(2026, 12, 20, 10, 0)
    assert cse_resume_time("Monthly CSE budget exceeded ($10.00 / 2000 paid queries)", now) == \
        datetime(2027, 1, 1)


def test_real_429_waits_for_googles_daily_reset():
    # midnight US Pacific: 07:00 UTC in daylight saving, 08:00 UTC in winter
    assert cse_resume_time("429 from Google", datetime(2026, 9, 27, 18, 53)) == datetime(2026, 9, 28, 7, 0)
    assert cse_resume_time("429 from Google", datetime(2026, 9, 28, 3, 0)) == datetime(2026, 9, 28, 7, 0)
    assert cse_resume_time("429 from Google", datetime(2026, 12, 15, 10, 0)) == datetime(2026, 12, 16, 8, 0)


def test_free_tier_stop_waits_for_the_daily_reset_not_next_month():
    reason = "Daily free quota reached (100/day). Resets at midnight US Pacific."
    assert cse_resume_time(reason, datetime(2026, 9, 28, 10, 32)) == datetime(2026, 9, 29, 7, 0)


def test_free_tier_refuses_past_the_daily_limit(monkeypatch):
    import leads.google_rate_limit as g

    class _Usage:
        def __init__(self):
            self.total = 100
            self.refunds = 0

        def find_one_and_update(self, q, u, **k):
            self.total += 1
            return {"total_queries": self.total, "hourly_queries": {}}

        def update_one(self, q, u):
            self.refunds += 1

    usage = _Usage()
    monkeypatch.setattr(g, "usage_collection", usage)
    monkeypatch.setattr(g, "get_rate_limit_settings", lambda: {
        "rate_limit_enabled": True, "daily_limit": 100, "hourly_limit": 50,
        "monthly_budget_usd": 0.0, "cost_per_1000_queries": 5.0, "monthly_paid_query_limit": 0})
    allowed, reason = g.reserve_query_slot()
    assert not allowed and "Daily free quota" in reason and usage.refunds == 1


# ---- addresses are built on the company's domain, never a platform's ------------

def test_platform_domains_are_refused():
    assert company_email_domain("uk.linkedin.com") == ""
    assert company_email_domain("https://www.linkedin.com/in/someone") == ""
    assert company_email_domain("crunchbase.com") == ""


def test_company_domain_is_cleaned():
    assert company_email_domain("www.nvidia.com") == "nvidia.com"
    assert company_email_domain("https://Acme-Research.co.uk/about") == "acme-research.co.uk"
    assert company_email_domain("localhost") == ""


def test_extraction_does_not_freeze_the_event_loop(monkeypatch):
    """The model call runs on a thread: other requests keep being served
    while it waits (it froze the whole backend on 2026-09-28)."""
    import asyncio
    import time
    import platform_core.ladder as ladder
    import leads.ingestion as ing

    result = {"title": "Jane Roe - Head of Research", "link": "https://www.linkedin.com/in/jane-roe",
              "snippet": "s"}

    window = []

    def slow_model(**kw):
        window.append(time.monotonic())
        time.sleep(0.5)
        window.append(time.monotonic())
        # a grounded answer, so the call does not fall through to the regex parser
        return ({"leads": [{"name": "Jane Roe", "title": "Head of Research",
                            "linkedin_url": "https://www.linkedin.com/in/jane-roe"}]}, "haiku", [])

    monkeypatch.setattr(ladder, "escalate_json", slow_model)
    ticks = []

    async def other_requests():
        for _ in range(8):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.05)

    async def main():
        await asyncio.gather(ing.extract_leads_from_google_results([result], "q"), other_requests())

    asyncio.run(main())
    # other requests ticked while the model call was in flight (wall-clock
    # spread is not used: a loaded machine makes it noisy on its own)
    assert len(ticks) == 8
    start, end = window
    assert any(start < t < end for t in ticks)


def test_no_results_means_no_model_call(monkeypatch):
    import asyncio
    import platform_core.ladder as ladder
    import leads.ingestion as ing
    calls = []
    monkeypatch.setattr(ladder, "escalate_json",
                        lambda **kw: calls.append(kw) or ({"leads": [{"name": "John Doe"}]}, "haiku", []))
    assert asyncio.run(ing.extract_leads_from_google_results([], "q")) == []
    assert calls == []


def test_extraction_runs_in_small_batches_and_keeps_the_real_snippet(monkeypatch):
    import asyncio
    import json
    import platform_core.ladder as ladder
    import leads.ingestion as ing
    results = [{"title": f"P{i} - Head of Research", "link": f"https://www.linkedin.com/in/p{i}",
                "snippet": f"snippet {i}"} for i in range(12)]
    prompts = []

    def fake(**kw):
        prompts.append(kw["user"])
        batch = json.loads(kw["user"].split("Search results:\n", 1)[1].split("\n\nReturn", 1)[0])
        data = {"leads": [{"name": r["title"].split(" - ")[0], "title": "Head of Research",
                           "linkedin_url": r["link"]} for r in batch]}
        return data, "haiku", []

    monkeypatch.setattr(ladder, "escalate_json", fake)
    leads = asyncio.run(ing.extract_leads_from_google_results(results, "q"))
    # 3 results per call (2026-10-15: five-result calls ran past the 180s limit)
    assert len(prompts) == 4 and len(leads) == 12
    assert leads[0]["snippet"] == "snippet 0"
    assert "email_candidate" not in prompts[0] and "\n  " not in prompts[0]


def test_invented_leads_are_dropped():
    from leads.ingestion import grounded_leads
    results = [{"link": "https://uk.linkedin.com/in/jane-roe-123?trk=x", "title": "Jane Roe - Head of Insights",
                "snippet": "Jane Roe leads consumer research at Acme."}]
    leads = [{"name": "Jane Roe", "linkedin_url": "https://www.linkedin.com/in/jane-roe-123/"},
             {"name": "John Doe", "linkedin_url": "https://www.linkedin.com/in/johndoe"},
             {"name": "Jane Roe", "linkedin_url": ""},
             {"name": "Mary Major", "linkedin_url": ""}]
    kept = grounded_leads(leads, results)
    assert [l["name"] for l in kept] == ["Jane Roe", "Jane Roe"]


def test_company_pages_are_not_people():
    from leads.ingestion import grounded_leads
    results = [{"link": "https://kr.linkedin.com/company/dn-automotive-corporation", "title": "DN Automotive", "snippet": ""}]
    assert grounded_leads([{"name": "DN Automotive",
                            "linkedin_url": "https://kr.linkedin.com/company/dn-automotive-corporation"}], results) == []


def test_no_address_is_rendered_on_a_platform_domain():
    assert not render_pattern_email("{first}.{last}@{domain}", "Radar", "Healthcare", "uk.linkedin.com")
    assert render_pattern_email("{first}.{last}@{domain}", "Jane", "Doe", "www.acme.com") == "jane.doe@acme.com"
