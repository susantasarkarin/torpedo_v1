"""
Profile completion percentage - the floor bug.

calculate_profile_completion used to average across all 14 profile fields,
five of which (first_name, last_name, email, country, language) are mandatory
at signup or default automatically. A brand-new account with nothing else
filled in therefore always reported ~36% complete, and could never read lower
regardless of actual engagement - both the admin dashboard and the panelist's
own progress ring were showing a number that didn't mean what it claimed to.
"""

from backend.routers.panel import calculate_profile_completion, _PROFILE_COMPLETION_OPTIONAL_FIELDS


def _signup_only_panelist():
    """What every account looks like the instant it's created - the five
    signup-mandatory fields set, nothing optional touched."""
    return {
        "first_name": "Asha", "last_name": "Rao", "email": "asha@example.com",
        "country": "India", "language": "English",
    }


def test_brand_new_signup_reports_zero_not_a_floor():
    assert calculate_profile_completion(_signup_only_panelist()) == 0


def test_fully_optional_profile_reports_100():
    panelist = _signup_only_panelist()
    for f in _PROFILE_COMPLETION_OPTIONAL_FIELDS:
        panelist[f] = "x"
    assert calculate_profile_completion(panelist) == 100


def test_partial_optional_completion_is_proportional():
    panelist = _signup_only_panelist()
    panelist["phone"] = "+91-9000000000"
    panelist["city"] = "Pune"
    # 2 of 9 optional fields
    expected = int((2 / len(_PROFILE_COMPLETION_OPTIONAL_FIELDS)) * 100)
    assert calculate_profile_completion(panelist) == expected


def test_mandatory_fields_never_move_the_number():
    """Filling in more of the ALREADY-mandatory fields (e.g. re-saving name)
    must not change completion - only the optional fields should."""
    with_mandatory_only = calculate_profile_completion(_signup_only_panelist())
    stripped = {"email": "x@example.com"}  # even less mandatory data present
    assert calculate_profile_completion(stripped) == with_mandatory_only == 0
