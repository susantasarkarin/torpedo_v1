"""
LinkedIn query semantics -- site: filter dropped from the Qwen prompt,
downstream /in/ filtering unchanged
========================================================================

2026-09-27 finding: for the main WebSearch job pipeline, ingestion.py's
search_linkedin_leads() strips any "site:linkedin.com..." fragment from the
query before it ever reaches Google (deliberately -- "no site: restriction
so all countries are covered") and instead relies entirely on downstream
filtering to keep only LinkedIn profile results:
  1. the extraction prompt instructs the model to only return linkedin.com/in/
     URLs and skip company/group/directory pages, and
  2. parse_extracted_leads() hard-discards any lead missing a linkedin_url.

This meant icp_query_ai.py's prompt telling Qwen to write
"site:linkedin.com/in/ ..." queries was decorative -- discarded before
Google ever saw it. Fixed: the prompt now tells Qwen NOT to add a site:
filter (freeing that space for title/company/industry/seniority variety)
and explains why. This file locks in:
  - the prompt no longer asks for a site: filter,
  - a query without one still comes back untouched (no site: requirement
    was ever enforced by _clean_queries), and
  - the downstream safety net (extraction prompt wording + the
    discard-if-no-linkedin_url rule) is unchanged and still there --
    that's what makes dropping the upstream site: instruction safe.

None of this touches ingestion_vm.py (which still forces its own
site:linkedin.com/in/ unconditionally) or the CSE quota work.
"""
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads.icp_config import DEFAULT_ICPS
from leads import query_variants_ai as qv
from leads.icp_query_ai import generate_icp_queries

BIM = next(i for i in DEFAULT_ICPS if i["slug"] == "bimwave")


# ============================================
# THE PROMPT ITSELF, AND A SITE:-FREE QUERY PASSES THROUGH
# ============================================

def test_prompts_tell_the_model_not_to_add_a_site_filter():
    for tpl in (qv._VARIATIONS, qv._FRESH):
        assert "no site: filters" in tpl.lower()


def test_a_site_filter_the_model_adds_anyway_is_stripped():
    raw = ['site:linkedin.com/in/ "BIM Manager" India', '"BIM Manager" India Building Information Modelling']
    with patch.object(qv, "_ask", return_value=raw):
        out = generate_icp_queries(BIM, count=5, leads_per_icp={})
    assert out == ['"BIM Manager" India', '"BIM Manager" India Building Information Modelling']


# ============================================
# DOWNSTREAM /in/ FILTERING IS UNCHANGED (the safety net that makes
# dropping the upstream site: instruction safe)
# ============================================

@pytest.fixture
def ingestion(monkeypatch):
    fake_db = types.ModuleType("database")
    fake_db.get_client = lambda: MagicMock()
    monkeypatch.setitem(sys.modules, "database", fake_db)
    sys.modules.pop("leads.ingestion", None)
    from leads import ingestion as mod
    yield mod
    sys.modules.pop("leads.ingestion", None)


def test_extraction_prompt_still_requires_a_linkedin_in_url(ingestion):
    prompt = ingestion.build_extraction_prompt(
        [{"title": "Jane Doe - BIM Manager | LinkedIn",
          "link": "https://www.linkedin.com/in/janedoe", "snippet": "..."}],
        query="BIM Manager India",
    )
    assert "linkedin.com/in/" in prompt
    assert "only /in/ profile urls" in prompt.lower()
    assert "skip company pages" in prompt.lower()


def test_a_lead_missing_linkedin_url_is_discarded_even_with_a_name(ingestion):
    """The hard enforcement point: a name alone is not enough to keep a
    lead -- it must carry a linkedin_url, regardless of what the upstream
    query looked like."""
    data = {"leads": [
        {"name": "Jane Doe", "linkedin_url": "https://linkedin.com/in/janedoe"},
        {"name": "No URL Person", "linkedin_url": ""},
        {"name": "", "linkedin_url": "https://linkedin.com/in/noname"},
    ]}
    leads = ingestion.parse_extracted_leads(data)
    assert len(leads) == 1
    assert leads[0]["name"] == "Jane Doe"


@pytest.mark.parametrize("query", [
    "site:linkedin.com/in/ \"BIM Manager\" India",   # old-style, still possible if a model ignores the instruction
    "site:linkedin.com \"BIM Manager\" India",        # the previously-shipped-then-reverted variant
    "\"BIM Manager\" India",                          # the new, expected shape
])
def test_any_site_variant_or_none_reaches_google_with_the_filter_stripped(ingestion, query):
    """Whatever a query looks like by the time it reaches
    search_linkedin_leads(), any site:linkedin.com... fragment is stripped
    before Google ever sees it -- this is the mechanism that makes the
    prompt's site: instruction (old or new) irrelevant to what Google
    actually receives."""
    captured = {}

    async def fake_perform_google_search(search_query, num_results, start=1):
        captured["query"] = search_query
        return []  # short-circuits before extraction is ever reached

    with patch.object(ingestion, "get_cached_response", return_value=None), \
         patch.object(ingestion, "take_stashed_results", return_value=None), \
         patch.object(ingestion, "perform_google_search", new=fake_perform_google_search):
        asyncio_run = __import__("asyncio").new_event_loop().run_until_complete
        asyncio_run(ingestion.search_linkedin_leads(query, skip_cache=True))

    assert "site:linkedin" not in captured["query"].lower()
    assert "bim manager" in captured["query"].lower()
