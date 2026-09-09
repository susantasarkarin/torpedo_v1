"""
Security-audit finding (2026-09-09): every request body field that gets
serialized directly into a real LLM prompt was unbounded — a caller with the
right permission could tie up this deployment's single local-inference slot
(a 2-vCPU box, see docs/LOCAL_LLM_RUNBOOK.md) with an arbitrarily large
payload. Pure Pydantic-validation tests, no FastAPI/DB fixtures needed — the
guard lives entirely in the request model.
"""

import pytest
from pydantic import ValidationError

from app.emailai.routers import IngestEmailRequest
from app.leadgen.routers import MAX_AI_CONTEXT_BYTES, EvaluateIcpRequest, GenerateLeadsRequest


def test_evaluate_icp_rejects_an_oversized_prospect_context():
    oversized = {"note": "x" * (MAX_AI_CONTEXT_BYTES + 1)}
    with pytest.raises(ValidationError):
        EvaluateIcpRequest(prospect_context=oversized)


def test_evaluate_icp_accepts_a_reasonable_prospect_context():
    req = EvaluateIcpRequest(prospect_context={"industry": "software", "country": "us"})
    assert req.prospect_context["industry"] == "software"


def test_generate_leads_rejects_an_oversized_internal_context():
    oversized = {"note": "x" * (MAX_AI_CONTEXT_BYTES + 1)}
    with pytest.raises(ValidationError):
        GenerateLeadsRequest(site_url="https://example.com", internal_context=oversized)


def test_generate_leads_accepts_the_default_empty_context():
    req = GenerateLeadsRequest(site_url="https://example.com")
    assert req.internal_context == {}


def test_ingest_email_rejects_a_body_over_the_length_cap():
    with pytest.raises(ValidationError):
        IngestEmailRequest(
            provider="gmail", provider_message_id="m1", from_address="a@b.com", to_address="c@d.com",
            subject="hi", body="x" * 100_001,
        )


def test_ingest_email_accepts_a_normal_body():
    req = IngestEmailRequest(
        provider="gmail", provider_message_id="m1", from_address="a@b.com", to_address="c@d.com",
        subject="hi", body="a perfectly ordinary email body",
    )
    assert req.body == "a perfectly ordinary email body"
