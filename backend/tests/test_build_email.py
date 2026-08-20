"""Guards EmailPatternSystem.build_email against emitting non-addresses.

Five call sites in background_job_scheduler write build_email's result straight
onto the lead, each guarded only by `if built:`. So anything it returns that is
not a real address gets persisted — which is where the bare local parts
(`tdavis`, `mparker`, `l.fuchs`) in leads_raw/leads_enriched came from.
"""

import pytest

from leads.email_pattern_system import EmailPatternSystem


class _NoDbPatternSystem(EmailPatternSystem):
    """build_email only needs get_pattern; stub it so no Mongo is required."""

    def __init__(self, pattern=None, confidence=0.9):
        self._pattern = pattern
        self._confidence = confidence

    def get_pattern(self, domain):
        if self._pattern is None:
            return None
        return {"pattern": self._pattern, "confidence": self._confidence}


def test_pattern_without_domain_suffix_is_completed():
    """A stored pattern of "{f}{last}" must not yield a bare local part."""
    ps = _NoDbPatternSystem("{f}{last}")
    email, conf = ps.build_email("Tiffany", "Davis", "nerdwallet.com")
    assert email == "tdavis@nerdwallet.com"
    assert conf > 0


def test_missing_domain_is_rejected_not_persisted():
    ps = _NoDbPatternSystem("{f}{last}")
    email, conf = ps.build_email("Tiffany", "Davis", "")
    assert email == ""
    assert conf == 0.0


def test_empty_last_name_does_not_produce_trailing_dot():
    """"{first}.{last}@{domain}" with no surname gives "angela.@corp.com"."""
    ps = _NoDbPatternSystem("{first}.{last}@{domain}")
    email, conf = ps.build_email("Angela", "", "corp.com")
    assert email == ""
    assert conf == 0.0


def test_normal_case_still_works():
    ps = _NoDbPatternSystem("{first}.{last}@{domain}")
    email, conf = ps.build_email("Marina", "Deiana", "fieldcare.it")
    assert email == "marina.deiana@fieldcare.it"
    assert conf > 0


def test_fallback_pattern_when_domain_unknown():
    ps = _NoDbPatternSystem(None)
    email, conf = ps.build_email("Erin", "McDonnell", "greenbook.com")
    assert email == "erin.mcdonnell@greenbook.com"
    assert conf == pytest.approx(0.2)


def test_placeholder_domain_is_rejected():
    """RFC 2606 reserved names are nobody's address."""
    ps = _NoDbPatternSystem("{first}.{last}@{domain}")
    email, conf = ps.build_email("Ken", "Evans", "domain.com")
    assert email == ""
    assert conf == 0.0


# ── The shared renderer ────────────────────────────────────────────────────
# apply_pattern_to_domain_leads used to format patterns itself, so every guard
# in build_email was bypassed there — and that path writes to BOTH
# leads_enriched and leads_raw, targeting leads with no email, which is exactly
# the state the repair script leaves behind. Repair and enrichment were undoing
# each other. Both now go through render_pattern_email.

from leads.email_pattern_system import render_pattern_email


@pytest.mark.parametrize("pattern,first,last,domain,expected", [
    ("{f}{last}", "Tiffany", "Davis", "nerdwallet.com", "tdavis@nerdwallet.com"),
    ("{first}.{last}@{domain}", "Marina", "Deiana", "fieldcare.it", "marina.deiana@fieldcare.it"),
    ("{first}@{domain}", "Erin", "", "greenbook.com", "erin@greenbook.com"),
])
def test_renderer_valid_cases(pattern, first, last, domain, expected):
    assert render_pattern_email(pattern, first, last, domain) == expected


@pytest.mark.parametrize("pattern,first,last,domain", [
    ("{f}{last}", "Tiffany", "Davis", ""),            # no domain -> bare local part
    ("{first}.{last}@{domain}", "Angela", "", "corp.com"),  # trailing dot
    ("{first}.{last}@{domain}", "Ken", "Evans", "domain.com"),  # reserved domain
    ("{first}.{last}@{domain}", "", "Davis", "corp.com"),   # no first name
    ("{nope}@{domain}", "Ken", "Evans", "corp.com"),        # unknown placeholder
])
def test_renderer_rejects_unusable(pattern, first, last, domain):
    assert render_pattern_email(pattern, first, last, domain) is None


def test_renderer_is_what_build_email_uses():
    """build_email must not re-implement rendering."""
    import inspect
    from leads.email_pattern_system import EmailPatternSystem
    src = inspect.getsource(EmailPatternSystem.build_email)
    assert "render_pattern_email" in src
    assert "pattern.format(" not in src


def test_bulk_applier_uses_the_renderer():
    import inspect
    from leads.email_pattern_system import EmailPatternSystem
    src = inspect.getsource(EmailPatternSystem.apply_pattern_to_domain_leads)
    assert "render_pattern_email" in src
    assert "pattern_str.format(" not in src
