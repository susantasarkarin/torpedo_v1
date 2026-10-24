"""Role and system mailboxes are kept out of every lead source at ingestion."""

import pytest

from leads.canonical_ingestion import _reject_non_person_email


@pytest.mark.parametrize("email,reason", [
    ("info@dscafrica.com", "role_address"),
    ("contactus@mares.ci", "role_address"),
    ("contact.us@acme.in", "role_address"),
    ("noreply@acme.com", "system_address"),
])
def test_nameless_mailbox_is_skipped(email, reason):
    assert _reject_non_person_email({"email": email}) == reason


def test_person_found_by_search_keeps_record_but_loses_role_address():
    lead = {"email": "info@acme.com", "linkedin_url": "https://linkedin.com/in/jane"}
    assert _reject_non_person_email(lead) is None
    assert lead["email"] is None


def test_real_person_passes_untouched():
    lead = {"email": "natasha@sproutstrategy.com"}
    assert _reject_non_person_email(lead) is None
    assert lead["email"] == "natasha@sproutstrategy.com"
