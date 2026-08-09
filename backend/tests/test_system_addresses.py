"""Guards the filter that keeps bounce notifiers out of the Leads table."""

import pytest

from leads.system_addresses import (
    is_mailable,
    is_malformed_address,
    is_placeholder_address,
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


@pytest.mark.parametrize("email", ["", None, "not-an-email", "two@@at.com", "no-at-sign",
                                   "firstname.lastname", "firstnamelastname"])
def test_malformed_is_unmailable_but_not_system(email):
    """Placeholder emails belong to real people and must not read as daemons.

    Enrichment leaves `firstname.lastname` on records for named contacts at
    real companies. Classing those as system addresses made a purge propose
    deleting a Kantar contact alongside the mailer-daemons.
    """
    assert is_malformed_address(email) is True
    assert is_system_address(email) is False   # not a daemon — just broken
    assert is_mailable(email) is False         # still never send to it
    assert is_promotable_lead_address(email) is False
    assert rejection_reason(email) == "malformed_address"


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
    "info@acme-research.com",
    "sales@acme-research.com",
    "support@acme-research.com",
    "billing@acme-research.com",
    "account-services@acme-research.com",
    "account.services@acme-research.com",
    "customerservice@acme-research.com",
    "careers@acme-research.com",
    # Read like infrastructure, routinely a real company's main contact.
    "mail@mafo-institut.com",
    "root@f1-solutions.net",
])
def test_role_mailboxes(email):
    assert is_role_address(email) is True
    assert is_system_address(email) is False
    # Excluded from promotion by default...
    assert is_promotable_lead_address(email) is False
    assert rejection_reason(email) == "role_address"
    # ...but available to callers that deliberately want them, and always
    # mailable: a shared mailbox is a real, reachable destination.
    assert is_promotable_lead_address(email, allow_role=True) is True
    assert is_mailable(email) is True


def test_role_opt_in_never_admits_system_addresses():
    assert is_promotable_lead_address("postmaster@acme-research.com", allow_role=True) is False


def test_split_address_handles_display_name_form():
    assert split_address("Mail Delivery Subsystem <MAILER-DAEMON@example.com>") == (
        "mailer-daemon", "example.com",
    )


def test_case_and_whitespace_insensitive():
    assert is_system_address("  POSTMASTER@Example.COM  ") is True


@pytest.mark.parametrize("email", REGRESSION_ADDRESSES)
def test_system_addresses_are_never_mailable(email):
    assert is_mailable(email) is False


# ── Enrichment placeholders ────────────────────────────────────────────────
# The enrichment prompts tell the model to produce "firstname.lastname@domain",
# and it sometimes returns the instruction instead of applying it. 192 prod
# leads carried one of these in the email field.

@pytest.mark.parametrize("email", [
    "firstname.lastname@domain.com",
    "firstnamelastname@example.com",
    "first_name.last_name@company.com",
    "yourname@yourcompany.com",
])
def test_templates_that_parse_are_still_placeholders(email):
    """These pass any shape check — they are nobody's address."""
    assert is_placeholder_address(email) is True
    assert is_malformed_address(email) is False
    assert is_mailable(email) is False


@pytest.mark.parametrize("email", ["firstname.lastname", "firstnamelastname"])
def test_bare_templates_are_both_malformed_and_placeholder(email):
    assert is_malformed_address(email) is True
    assert is_placeholder_address(email) is True
    assert is_mailable(email) is False


@pytest.mark.parametrize("email", ["hunter.evans", "roy.restivo", "pam_kaufman", "lmohmand"])
def test_local_part_only_is_unmailable(email):
    """The model dropped the domain. Real person, unusable address."""
    assert is_malformed_address(email) is True
    assert is_mailable(email) is False


@pytest.mark.parametrize("email", [
    "erin@greenbook.com",
    "marina.deiana@fieldcare.it",
    # A real surname that merely contains a template token.
    "john.firstnamer@realco.com",
])
def test_real_addresses_are_mailable(email):
    assert is_mailable(email) is True
