"""Lead Information backfill: fills empty fields only, from the lead's own mail."""

from scripts.backfill_lead_info import (
    department_for,
    derive_lead_info,
    seniority_for,
    signature_fields,
    split_name,
)


def test_last_comma_first_display_name():
    assert split_name("Kidd, Tim (KWLWG)") == ("Tim", "Kidd")
    assert split_name("Natasha Jarrah") == ("Natasha", "Jarrah")
    assert split_name("info@acme.com") == ("", "")


def test_seniority_uses_whole_words():
    assert seniority_for("Research Director") == "Director"  # not C-Level via "cto"
    assert seniority_for("Chief Research Officer") == "C-Level"
    assert seniority_for("Senior Project Manager") == "Manager"
    assert seniority_for("Analyst") == "IC"
    assert seniority_for("") is None


def test_junk_sender_titles_are_rejected():
    from scripts.backfill_lead_info import _clean_title
    for junk in ("Not specified", "Terms and Conditions", "865 Easton Road, Suite 200",
                 "www.theinsightsshop.com", "30-40%", "INDIA", "*Prodege, LLC*", "NA"):
        assert _clean_title(junk) is None, junk
    assert _clean_title("Vice President, Client Solutions") == "Vice President, Client Solutions"
    assert seniority_for("Vice President, Client Solutions") == "VP"
    assert _clean_title("Senior Field Coordinator") == "Senior Field Coordinator"


def test_department_from_title():
    assert department_for("Head of Fieldwork Operations") == "Research"
    assert department_for("Procurement Lead") == "Procurement"


def test_signature_ignores_the_quoted_thread():
    body = (
        "Thanks, will revert.\n\nPriya Shah | Senior Research Manager\n"
        "Mobile: +91 98200 12345\nlinkedin.com/in/priya-shah\n\n"
        "On Mon, 3 Mar 2025 at 10:00, Rahul <rahul@surveyfieldwork.com> wrote:\n"
        "> Rahul Sarkar | Director\n> Phone: +1 555 000 1111\n"
    )
    info = signature_fields(body)
    assert info["title"] == "Senior Research Manager"
    assert info["phone"] == "+91 98200 12345"
    assert info["linkedin_url"] == "https://www.linkedin.com/in/priya-shah"


def test_dates_and_ids_are_not_phone_numbers():
    assert "phone" not in signature_fields("Regards\nMin\n18.04.2019")
    assert "phone" not in signature_fields("Regards\nArul\nRef 223404411203")
    assert signature_fields("Regards\nBadri\n9778567983")["phone"] == "9778567983"
    assert signature_fields("Tel: (562) 2239 4189")["phone"] == "(562) 2239 4189"


def test_generic_tlds_have_no_country():
    from scripts.backfill_lead_info import country_for
    assert country_for("fabrise.co") is None
    assert country_for("sritechs.in") == "India"


def test_fills_only_empty_fields():
    lead = {"email": "tim.kidd@kantarworldpanel.co.uk", "name": "Kidd, Tim (KWLWG)",
            "first_name": "Kidd,", "title": "Panel Director", "company_domain": None}
    msgs = [{"sender_info": {"title": "Something Else", "location": "London"}, "body_plain": ""}]
    out = derive_lead_info(lead, msgs)
    assert out["first_name"] == "Tim" and out["last_name"] == "Kidd"
    assert out["company_domain"] == "kantarworldpanel.co.uk"
    assert out["country"] == "United Kingdom"
    assert out["location"] == "London"
    assert "title" not in out  # already set by someone
    assert out["seniority_level"] == "Director"


def test_personal_domain_is_not_a_company():
    out = derive_lead_info({"email": "buyer@gmail.com", "name": "A B"}, [])
    assert "company_domain" not in out
