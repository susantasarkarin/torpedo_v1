"""
Regression guard for the null-confidence hole: outreach_qualification.check_email
rejects a "Predicted" email with no email_pattern_confidence (see
test_outreach_qualification.py for that gate itself). This file locks in the
write side of the fix — every call site that can set email_status='Predicted'
must ALSO record a numeric email_pattern_confidence in the same write, so a
future edit can't quietly reopen the hole by writing status without confidence.

Covers, per site:
  - EmailPatternSystem.build_email_with_source(): never returns confidence=None
  - leads/canonical_ingestion.py::_discover_and_apply_email_pattern
  - leads/bounce_recovery.py::_update_enriched_email
  - leads/service.py::classify_single_lead (predicted_email branch)
"""
import os
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================
# build_email_with_source: confidence is never None
# ============================================

class _StubPatternSystem:
    """Stub out network/DB tiers so build_email_with_source runs offline."""

    def __init__(self, pattern_data=None, web_search_result=None):
        self._pattern_data = pattern_data
        self._web_search_result = web_search_result

    def get_pattern(self, domain):
        return self._pattern_data

    def _web_search_lookup(self, first_name, last_name, domain, company_name=""):
        return self._web_search_result


@pytest.mark.parametrize("pattern_data,web_search_result", [
    (None, None),  # nothing found anywhere -> falls through to blind guess
    ({"pattern": "{first}.{last}@{domain}", "confidence": 0.9, "source": "hunter_io"}, None),
    (None, {"email": "jane.doe@acme.com", "confidence": 0.7}),
])
def test_build_email_with_source_confidence_never_none(pattern_data, web_search_result):
    from leads.email_pattern_system import EmailPatternSystem
    stub = _StubPatternSystem(pattern_data, web_search_result)
    email, confidence, source = EmailPatternSystem.build_email_with_source(
        stub, "Jane", "Doe", "acme.com"
    )
    assert confidence is not None
    assert isinstance(confidence, float)


# ============================================
# canonical_ingestion._discover_and_apply_email_pattern
# ============================================

def test_discover_and_apply_email_pattern_always_sets_confidence_with_email():
    import leads.canonical_ingestion as ci

    class FakePS:
        def build_email_with_source(self, first, last, domain, company_name=""):
            return f"{first.lower()}.{last.lower()}@{domain}", 0.3, "guess"

        def _lookup_database(self, domain):
            return None

        def apply_pattern_to_domain_leads(self, domain, pattern):
            pass

    with patch("leads.email_pattern_system.get_pattern_system", return_value=FakePS()):
        normalized = {"first_name": "Jane", "last_name": "Doe", "company_domain": "acme.com"}
        ci._discover_and_apply_email_pattern(normalized)

    assert normalized["email"] == "jane.doe@acme.com"
    assert normalized["email_status"] == "Predicted"
    assert normalized.get("email_pattern_confidence") is not None
    assert normalized["email_pattern_confidence"] == 0.3


def test_discover_and_apply_email_pattern_no_email_no_confidence():
    """When nothing renderable is found, neither email nor confidence is set —
    check_email's own no_email check handles that case, not the confidence gate."""
    import leads.canonical_ingestion as ci

    class FakePS:
        def build_email_with_source(self, first, last, domain, company_name=""):
            return "", 0.0, "none"

        def _lookup_database(self, domain):
            return None

        def apply_pattern_to_domain_leads(self, domain, pattern):
            pass

    with patch("leads.email_pattern_system.get_pattern_system", return_value=FakePS()):
        normalized = {"first_name": "Jane", "last_name": "Doe", "company_domain": "acme.com"}
        ci._discover_and_apply_email_pattern(normalized)

    assert "email" not in normalized
    assert "email_pattern_confidence" not in normalized


# ============================================
# bounce_recovery._update_enriched_email
# ============================================

def test_bounce_recovery_update_enriched_email_writes_confidence_when_given():
    import leads.bounce_recovery as br

    fake_leads_db = {"leads_enriched": MagicMock()}

    br._update_enriched_email(fake_leads_db, ObjectId(), "jane.doe@acme.com",
                              "bounce_recovery_skrapp", confidence=0.9)

    args, kwargs = fake_leads_db["leads_enriched"].update_one.call_args
    set_doc = args[1]["$set"]
    assert set_doc["email_pattern_confidence"] == 0.9
    assert set_doc["email_status"] == "Predicted"


def test_bounce_recovery_alt_format_call_site_passes_low_confidence():
    """The disabled-by-default alt_format guesser must pass confidence=0.2
    explicitly, so the gate still blocks it if ever re-enabled without also
    fixing the underlying guess quality."""
    import inspect
    import leads.bounce_recovery as br
    src = inspect.getsource(br.attempt_recovery)
    assert 'confidence=0.2' in src


# ============================================
# service.classify_single_lead: predicted_email branch always sets confidence
# ============================================

def test_classify_single_lead_predicted_email_always_records_confidence():
    import leads.service as svc
    from leads.models import (
        AIClassificationOutput, AIClassificationLog, SeniorityLevel, Department,
        Persona, BuyingRole, Gender, CompanySize, Region,
    )

    raw_lead_id = str(ObjectId())
    raw_lead_doc = {
        "_id": ObjectId(raw_lead_id),
        "name": "Jane Doe",
        "title": "Director",
        "linkedin_url": "https://linkedin.com/in/janedoe",
        "email": None,  # no raw email -> forces the predicted_email branch
        "company_domain": "acme.com",
        "company_name": "Acme Inc",
    }

    classification_result = AIClassificationOutput(
        first_name="Jane", last_name="Doe",
        predicted_email="jane.doe@acme.com",  # the classifier's own blind guess
        seniority_level=SeniorityLevel.DIRECTOR if hasattr(SeniorityLevel, "DIRECTOR") else list(SeniorityLevel)[0],
        department=list(Department)[0],
        persona=list(Persona)[0],
        buying_role=list(BuyingRole)[0],
        gender=Gender.UNKNOWN if hasattr(Gender, "UNKNOWN") else list(Gender)[0],
        company_size=list(CompanySize)[0],
        region=list(Region)[0],
        company_name="Acme Inc",
        company_domain="acme.com",
        confidence_score=0.8,
    )
    classification_log = AIClassificationLog(
        raw_lead_id=raw_lead_id, linkedin_url=raw_lead_doc["linkedin_url"],
        prompt_used="x", model_used="x", success=True,
    )

    class FakePS:
        def build_email_with_source(self, first, last, domain, company_name=""):
            # Simulate: no verified source found, falls back to a blind guess
            return "jane.doe@acme.com", 0.2, "guess"

    with patch.object(svc, "leads_raw_collection") as fake_raw, \
         patch.object(svc, "leads_enriched_collection") as fake_enriched, \
         patch.object(svc, "classification_logs_collection") as fake_logs, \
         patch.object(svc, "classify_lead", return_value=(classification_result, classification_log)), \
         patch("leads.email_pattern_system.get_pattern_system", return_value=FakePS()):

        fake_raw.find_one.return_value = raw_lead_doc
        fake_enriched.update_one.return_value = SimpleNamespace(upserted_id=ObjectId())

        svc.classify_single_lead(raw_lead_id)

        # Find the leads_enriched.update_one call and inspect the $set payload
        assert fake_enriched.update_one.called
        _, kwargs_or_args = fake_enriched.update_one.call_args, None
        call = fake_enriched.update_one.call_args
        set_doc = call.args[1]["$set"] if call.args else call.kwargs["update"]["$set"]

    assert set_doc.get("email_status") == "Predicted"
    assert set_doc.get("email_pattern_confidence") is not None
    assert set_doc["email_pattern_confidence"] == 0.2
    assert set_doc.get("email_source") == "guess"
