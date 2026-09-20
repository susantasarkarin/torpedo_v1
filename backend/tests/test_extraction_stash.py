"""
LEAD EXTRACTION FAIL-CLOSED + RAW-RESULT STASH

Covers the 2026-09-20 fix: when the extraction model is unreachable, the
extractor must return nothing (not regex-parse a LinkedIn headline into a
company name and guess an email), must keep the paid-for raw search results,
and must not mark the query as done. Also covers the domain-guess guard.

No live Mongo or model: `database` is stubbed before leads.ingestion imports it
(that module builds its Mongo handles at import time), and the model call is
patched.
"""
import asyncio
import os
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")


class FakeCollection:
    """Just enough of a pymongo collection for the stash: upsert + atomic claim."""

    def __init__(self):
        self.docs = {}

    def update_one(self, flt, update, upsert=False):
        _id = flt["_id"]
        doc = self.docs.get(_id)
        if doc is None:
            if not upsert:
                return
            doc = {"_id": _id, **update.get("$setOnInsert", {})}
            self.docs[_id] = doc
        doc.update(update.get("$set", {}))
        for k, v in update.get("$inc", {}).items():
            doc[k] = doc.get(k, 0) + v

    def find_one_and_update(self, flt, update):
        doc = self.docs.get(flt["_id"])
        if not doc or doc.get("status") != flt.get("status"):
            return None
        if doc["updated_at"] < flt["updated_at"]["$gte"]:
            return None
        before = dict(doc)
        doc.update(update["$set"])
        return before


RESULTS = [{"title": "Zach Whitman - Scaling B2B SaaS products | LinkedIn",
            "link": "https://www.linkedin.com/in/zach-whitman",
            "snippet": "OpenTable. My focus is on setting clear strategy, building strong operating rhythms"}]


@pytest.fixture
def stash():
    from leads import extraction_stash
    return extraction_stash


@pytest.fixture
def coll():
    return FakeCollection()


# ---------------------------------------------------------------- the stash

def test_stash_then_take_round_trips_and_claims_once(stash, coll):
    assert stash.stash_unextracted_results("bim managers india", RESULTS, "outage", collection=coll)
    assert stash.take_stashed_results("bim managers india", collection=coll) == RESULTS
    # atomic claim: a second worker replaying the same query gets nothing
    assert stash.take_stashed_results("bim managers india", collection=coll) == []


def test_key_ignores_case_and_whitespace_but_not_page(stash, coll):
    stash.stash_unextracted_results("  BIM Managers India ", RESULTS, "outage", start=11, collection=coll)
    assert stash.take_stashed_results("bim managers india", start=1, collection=coll) == []
    assert stash.take_stashed_results("bim managers india", start=11, collection=coll) == RESULTS


def test_restash_after_failed_replay_makes_it_pending_again(stash, coll):
    stash.stash_unextracted_results("q", RESULTS, "outage", collection=coll)
    stash.take_stashed_results("q", collection=coll)
    stash.stash_unextracted_results("q", RESULTS, "outage again", collection=coll)
    assert stash.take_stashed_results("q", collection=coll) == RESULTS
    assert coll.docs[stash._key("q", 1)]["attempts"] == 2


def test_stale_stash_is_not_replayed(stash, coll):
    stash.stash_unextracted_results("q", RESULTS, "outage", collection=coll)
    coll.docs[stash._key("q", 1)]["updated_at"] = datetime.utcnow() - timedelta(days=stash.MAX_AGE_DAYS + 1)
    assert stash.take_stashed_results("q", collection=coll) == []


def test_empty_results_are_never_stashed(stash, coll):
    assert stash.stash_unextracted_results("q", [], "outage", collection=coll) is False
    assert coll.docs == {}


def test_database_failure_never_raises_into_the_search(stash):
    broken = MagicMock()
    broken.update_one.side_effect = RuntimeError("mongo down")
    broken.find_one_and_update.side_effect = RuntimeError("mongo down")
    assert stash.stash_unextracted_results("q", RESULTS, "outage", collection=broken) is False
    assert stash.take_stashed_results("q", collection=broken) == []


# ------------------------------------------------- ingestion: fail closed

@pytest.fixture
def ingestion(monkeypatch):
    """Import leads.ingestion with Mongo stubbed out (it builds handles at import)."""
    fake_db = types.ModuleType("database")
    fake_db.get_client = lambda: MagicMock()
    monkeypatch.setitem(sys.modules, "database", fake_db)
    sys.modules.pop("leads.ingestion", None)
    from leads import ingestion as mod
    yield mod
    sys.modules.pop("leads.ingestion", None)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_model_outage_returns_nothing_not_regex_junk(ingestion):
    with patch("leads.bedrock_client.converse_json_object", side_effect=RuntimeError("401 Unauthorized")), \
         patch.object(ingestion, "stash_unextracted_results") as stash_mock:
        out = _run(ingestion.extract_leads_from_google_results(RESULTS, "b2b saas", start=11))
    assert out == []
    stash_mock.assert_called_once()
    assert stash_mock.call_args.args[0] == "b2b saas"
    assert stash_mock.call_args.args[1] == RESULTS
    assert stash_mock.call_args.kwargs["start"] == 11


def test_model_answering_with_nothing_still_uses_regex_path(ingestion):
    """Only an outage fails closed; a model that answered keeps the old behaviour."""
    with patch("leads.bedrock_client.converse_json_object", return_value={"leads": []}), \
         patch.object(ingestion, "stash_unextracted_results") as stash_mock:
        _run(ingestion.extract_leads_from_google_results(RESULTS, "b2b saas"))
    stash_mock.assert_not_called()


def test_outage_does_not_cache_or_mark_the_query_done(ingestion):
    """An empty return must leave no cache entry, or the query would look finished."""
    with patch.object(ingestion, "get_cached_response", return_value=None), \
         patch.object(ingestion, "take_stashed_results", return_value=[]), \
         patch.object(ingestion, "perform_google_search", return_value=RESULTS), \
         patch.object(ingestion, "cache_response") as cache_mock, \
         patch.object(ingestion, "stash_unextracted_results"), \
         patch("leads.bedrock_client.converse_json_object", side_effect=RuntimeError("outage")):
        out = _run(ingestion.search_linkedin_leads("b2b saas", num_results=10))
    assert out == []
    cache_mock.assert_not_called()


def test_rerun_replays_stash_without_spending_google_quota(ingestion):
    google = MagicMock()
    with patch.object(ingestion, "get_cached_response", return_value=None), \
         patch.object(ingestion, "take_stashed_results", return_value=RESULTS), \
         patch.object(ingestion, "perform_google_search", google), \
         patch.object(ingestion, "extract_leads_from_google_results",
                      return_value=[{"name": "Zach Whitman"}]) as extract:
        _run(ingestion.search_linkedin_leads("b2b saas", num_results=10, deduplicate=False))
    google.assert_not_called()
    assert extract.call_args.args[0] == RESULTS


# ------------------------------------------------------ domain-guess guard

@pytest.mark.parametrize("company,expected", [
    ("Bandhan Bank", "bandhanbank.com"),
    ("Hindustan Unilever Limited", "hindustanunilever.com"),
    ("Ipsos", "ipsos.com"),
    ("OpenTable. My focus is on setting clear strategy, building strong operating "
     "rhythms, and helping teams ship ...", ""),
    ("Quantitative Market Research Analyst at a large firm in Mumbai India", ""),
])
def test_domain_guess_rejects_sentence_length_company_names(ingestion, company, expected):
    assert ingestion._infer_company_domain(company, "") == expected


def test_explicit_domain_in_snippet_still_wins_over_the_guard(ingestion):
    assert ingestion._infer_company_domain(
        "a very long headline that is obviously not a company name at all", "visit www.acme.io today"
    ) == "acme.io"
