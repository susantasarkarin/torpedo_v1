"""
PERSIST() MIRRORS outreach_bucket EVEN FOR REJECT/REVIEW
=========================================================

2026-09-26 finding: enrollment (_build_basket_enrollment_query in
cold_outreach_router.py) reads leads_enriched.classification_basket, a field
set by a SEPARATE, earlier, rule-based classifier at ingestion
(canonical_ingestion.compute_icp_basket) -- never by outreach_bucket. Before
this fix, persist() mirrored outreach_bucket onto leads_enriched only for the
three accepted service-line buckets, so a REJECT/REVIEW verdict here was
invisible downstream no matter what: measured empirically, 5,569 REJECT- and
3,190 REVIEW-bucketed leads had already been enrolled and mailed, because their
leads_enriched doc kept whatever classification_basket the earlier classifier
had already assigned.

These tests pin the fix: outreach_bucket is mirrored unconditionally (so the
enrollment query's new exclusion clause has something to act on), while
classification_basket / icp_segment / classification_basket_name are mirrored
ONLY for the three accepted buckets, exactly as before -- REJECT/REVIEW must
never set or touch classification_basket.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import bucket_classifier as bc
from leads.outreach_config import REJECT_BUCKET, REVIEW_BUCKET

ENRICHED_ID = str(ObjectId())


@pytest.fixture
def fake_collections():
    """Patch leads_raw (module-level) and its .database["leads_enriched"] so
    persist() writes into inspectable mocks instead of a real Mongo."""
    fake_raw = MagicMock()
    fake_enriched = MagicMock()
    fake_raw.database = {"leads_enriched": fake_enriched}
    with patch.object(bc, "leads_raw", fake_raw):
        yield fake_raw, fake_enriched


def _lead(**kw):
    base = {"_id": "raw1", "enriched_lead_id": ENRICHED_ID}
    base.update(kw)
    return base


def test_reject_mirrors_outreach_bucket_but_not_basket(fake_collections):
    fake_raw, fake_enriched = fake_collections
    result = {"bucket": REJECT_BUCKET, "confidence": 0.95, "reason": "student", "method": "cheap"}
    assert bc.persist(_lead(), result) is True

    fake_enriched.update_one.assert_called_once()
    (flt, update) = fake_enriched.update_one.call_args.args
    assert flt == {"_id": ObjectId(ENRICHED_ID)}
    mirror = update["$set"]
    assert mirror["outreach_bucket"] == REJECT_BUCKET
    assert "classification_basket" not in mirror
    assert "icp_segment" not in mirror
    assert "classification_basket_name" not in mirror


def test_review_mirrors_outreach_bucket_but_not_basket(fake_collections):
    fake_raw, fake_enriched = fake_collections
    result = {"bucket": REVIEW_BUCKET, "confidence": 0.0, "reason": "unsure",
             "method": "low_confidence_no_escalation", "proposed_bucket": "SFW"}
    assert bc.persist(_lead(), result) is True

    mirror = fake_enriched.update_one.call_args.args[1]["$set"]
    assert mirror["outreach_bucket"] == REVIEW_BUCKET
    assert "classification_basket" not in mirror


def test_reject_vetoed_by_fit_signal_also_mirrors_review(fake_collections):
    """The 2026-09-20 title-fit veto reroutes a model REJECT to REVIEW; that
    verdict must reach leads_enriched exactly like any other REVIEW."""
    fake_raw, fake_enriched = fake_collections
    result = {"bucket": REVIEW_BUCKET, "confidence": 0.95,
              "reason": "model rejected, but the title carries a strong BIM signal",
              "method": "reject_vetoed_fit_signal", "proposed_bucket": REJECT_BUCKET}
    bc.persist(_lead(), result)
    mirror = fake_enriched.update_one.call_args.args[1]["$set"]
    assert mirror["outreach_bucket"] == REVIEW_BUCKET
    assert "classification_basket" not in mirror


def test_accepted_bucket_still_mirrors_basket_exactly_as_before(fake_collections):
    fake_raw, fake_enriched = fake_collections
    result = {"bucket": "BIM", "confidence": 0.9, "reason": "BIM Manager", "method": "cheap"}
    bc.persist(_lead(), result)
    mirror = fake_enriched.update_one.call_args.args[1]["$set"]
    assert mirror["outreach_bucket"] == "BIM"
    assert mirror["classification_basket"] == "C"
    assert mirror["icp_segment"] == "bimwave"
    assert mirror["classification_basket_name"] == "BIMwave"


def test_no_enriched_id_means_no_mirror_attempt(fake_collections):
    fake_raw, fake_enriched = fake_collections
    result = {"bucket": REJECT_BUCKET, "confidence": 0.9, "reason": "student", "method": "cheap"}
    bc.persist(_lead(enriched_lead_id=None), result)
    fake_enriched.update_one.assert_not_called()


def test_mirror_failure_never_raises_or_blocks_the_raw_write(fake_collections):
    fake_raw, fake_enriched = fake_collections
    fake_enriched.update_one.side_effect = RuntimeError("mongo down")
    result = {"bucket": REJECT_BUCKET, "confidence": 0.9, "reason": "student", "method": "cheap"}
    assert bc.persist(_lead(), result) is True
    fake_raw.update_one.assert_called_once()   # leads_raw write still happened


def test_dry_run_never_writes_anything(fake_collections):
    fake_raw, fake_enriched = fake_collections
    result = {"bucket": REJECT_BUCKET, "confidence": 0.9, "reason": "student", "method": "cheap"}
    assert bc.persist(_lead(), result, dry_run=True) is False
    fake_raw.update_one.assert_not_called()
    fake_enriched.update_one.assert_not_called()
