"""Guards the filter that keeps bounce notifiers out of the Leads table."""

import pytest

from leads.system_addresses import (
    is_promotable_lead_address,
    is_role_address,
    is_system_address,
    rejection_reason,
    split_address,
)


# The exact addresses that reached production and were shown in the Leads UI
# as named leads with a company and an ICP segment.
REGRESSION_ADDRESSES = [
    "postmaster@precisionopinion.com",
    "postmaster@walkerinfo.com",
    "postmaster@goascribe.com",
    "postmaster@marketresponse.com",
    "postmaster@oxsusvadesecure.com",
    "postmaster@burke.com",
    "mailer-daemon@googlemail.com",
    "MAILER-DAEMON@oxsusvadesecure.com",
]


@pytest.mark.parametrize("email", REGRESSION_ADDRESSES)
def test_production_bounce_addresses_are_rejected(email):
    assert is_system_address(email) is True
    assert is_promotable_lead_address(email) is False
    assert rejection_reason(email) == "system_address"


@pytest.mark.parametrize("email", [
    "noreply@example.com",
    "no-reply@example.com",
    "noreply2@example.com",
    "donotreply@example.com",
    "do-not-reply@example.com",
    "bounce@example.com",
    "bounces@example.com",
    "bounce-12345@example.com",
    "notifications@example.com",
    "alerts@example.com",
    "auto-reply@example.com",
    "root@example.com",
    "abuse@example.com",
    "delivery-status@example.com",
])
def test_system_locals_and_prefixes(email):
    assert is_system_address(email) is True


@pytest.mark.parametrize("email", [
    # Every one of these has a different local part, so an exact-match list
    # would let each become its own unique junk lead.
    "bounces+12345-abc=example.com@sender.net",
    "msprvs1=1234abc=bounces@sender.net",
    "prvs=1234abcd=user@example.com",
    "srs0=xyz=ab=example.com=user@forwarder.net",
    "b1234567-abc@sender.net",
])
def test_verp_and_srs_bounce_locals(email):
    assert is_system_address(email) is True


@pytest.mark.parametrize("email", [
    "anything@bounce.example.com",
    "someone@mailer-daemon.example.net",
])
def test_bounce_subdomains(email):
    assert is_system_address(email) is True


@pytest.mark.parametrize("email", ["", None, "not-an-email", "two@@at.com", "no-at-sign"])
def test_unparseable_counts_as_system(email):
    """An address we cannot read is not one we should be mailing."""
    assert is_system_address(email) is True


@pytest.mark.parametrize("email", [
    "erin@greenbook.com",
    "marina.deiana@fieldcare.it",
    "benjamin.banda@estudiosilviaroca.com",
    "karolina.reczek@grupa4p.pl",
    "andrea.romo@optum.com",
    # Real people whose names merely contain a filtered word.
    "robert.bounceford@example.com",
    "alerta.garcia@example.com",
    "postmasterson@example.com",
])
def test_real_people_are_not_rejected(email):
    assert is_system_address(email) is False
    assert is_promotable_lead_address(email) is True
    assert rejection_reason(email) is None


@pytest.mark.parametrize("email", [
    "info@example.com",
    "sales@example.com",
    "support@example.com",
    "billing@example.com",
    "account-services@example.com",
    "account.services@example.com",
    "customerservice@example.com",
    "careers@example.com",
])
def test_role_mailboxes(email):
    assert is_role_address(email) is True
    assert is_system_address(email) is False
    # Excluded from promotion by default...
    assert is_promotable_lead_address(email) is False
    assert rejection_reason(email) == "role_address"
    # ...but available to callers that deliberately want them.
    assert is_promotable_lead_address(email, allow_role=True) is True


def test_role_opt_in_never_admits_system_addresses():
    assert is_promotable_lead_address("postmaster@example.com", allow_role=True) is False


def test_split_address_handles_display_name_form():
    assert split_address("Mail Delivery Subsystem <MAILER-DAEMON@example.com>") == (
        "mailer-daemon", "example.com",
    )


def test_case_and_whitespace_insensitive():
    assert is_system_address("  POSTMASTER@Example.COM  ") is True
