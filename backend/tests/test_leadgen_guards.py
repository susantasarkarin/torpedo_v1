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
    assert cse_resume_time("429 from Google", datetime(2026, 9, 27, 18, 53)) == datetime(2026, 9, 28, 8, 0)
    assert cse_resume_time("429 from Google", datetime(2026, 9, 28, 3, 0)) == datetime(2026, 9, 28, 8, 0)


# ---- addresses are built on the company's domain, never a platform's ------------

def test_platform_domains_are_refused():
    assert company_email_domain("uk.linkedin.com") == ""
    assert company_email_domain("https://www.linkedin.com/in/someone") == ""
    assert company_email_domain("crunchbase.com") == ""


def test_company_domain_is_cleaned():
    assert company_email_domain("www.nvidia.com") == "nvidia.com"
    assert company_email_domain("https://Acme-Research.co.uk/about") == "acme-research.co.uk"
    assert company_email_domain("localhost") == ""


def test_no_address_is_rendered_on_a_platform_domain():
    assert not render_pattern_email("{first}.{last}@{domain}", "Radar", "Healthcare", "uk.linkedin.com")
    assert render_pattern_email("{first}.{last}@{domain}", "Jane", "Doe", "www.acme.com") == "jane.doe@acme.com"
