"""
ICP QUERY GENERATION REGRESSION TESTS
=====================================

Guards the fix for the ICP industry-leak bug: generate_search_queries() used to
sample from a generic ~60-industry module-level list instead of the active ICP's
own `industries`, producing off-ICP queries such as:

    "BIM Manager" Crypto India

These tests assert:
1. Every industry token in a generated query comes from the ICP's own config
2. An ICP with no industries produces queries with no industry term at all
3. Designations/countries also stay inside the ICP config
4. The generic global INDUSTRIES list is gone and cannot be reintroduced silently

Run with: pytest backend/tests/test_icp_query_generation.py -v
"""

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import scheduler
from leads.scheduler import generate_search_queries
from leads.icp_config import DEFAULT_ICPS


# ============================================
# HELPERS
# ============================================

def _icp(slug: str) -> dict:
    """Fetch a seeded ICP definition by slug."""
    for icp in DEFAULT_ICPS:
        if icp["slug"] == slug:
            return icp
    raise AssertionError(f"ICP '{slug}' not found in DEFAULT_ICPS")


def _config_from_icp(icp: dict) -> dict:
    """
    Build the query-generator config exactly the way scheduler_loop() does.
    Kept in sync with scheduler.py's ICP round-robin block.
    """
    return {
        "designations": icp.get("designations", []),
        "countries": icp.get("countries", []),
        "seniorities": icp.get("seniority_levels", []),
        "custom_query": icp.get("custom_context", ""),
        "industries": icp.get("industries", []),
    }


def _strip_known_tokens(query: str, config: dict) -> str:
    """
    Remove every token the config legitimately contributes, longest-first so
    that e.g. 'Civil Engineering' is consumed before 'Engineering'.
    Whatever remains is unaccounted-for text.
    """
    contributed = (
        list(config.get("designations", []))
        + list(config.get("countries", []))
        + list(config.get("industries", []))
        + list(config.get("seniorities", []))
    )
    custom = config.get("custom_query", "")
    if custom:
        contributed.append(custom)

    remainder = query
    for token in sorted(contributed, key=len, reverse=True):
        remainder = remainder.replace(f'"{token}"', " ").replace(token, " ")
    return " ".join(remainder.split())


# ============================================
# THE BUG FIX
# ============================================

def test_bim_icp_never_emits_foreign_industry():
    """
    THE REGRESSION TEST.

    No query generated for the BIM ICP may contain an industry term that is not
    in that ICP's own `industries` list. Previously '"BIM Manager" Crypto India'
    was reachable; the off-ICP industries below are the ones that used to leak.
    """
    bim = _icp("bimwave")
    config = _config_from_icp(bim)
    allowed = {i.lower() for i in bim["industries"]}

    # Industries that existed only in the deleted global list.
    foreign = {
        "crypto", "web3", "blockchain", "gaming", "fintech", "edtech",
        "healthtech", "biotech", "pharmaceuticals", "wealth management",
        "venture capital", "private equity", "legaltech", "proptech",
        "cybersecurity", "machine learning", "hrtech", "e-commerce",
        "entertainment", "insurance", "automotive", "cleantech",
    }
    assert not (foreign & allowed), "test fixture is stale: overlap with ICP"

    random.seed(1337)
    queries = generate_search_queries(config, count=200)
    assert queries, "generator returned nothing"

    for query in queries:
        lowered = query.lower()
        for bad in foreign:
            assert bad not in lowered, (
                f"off-ICP industry {bad!r} leaked into BIM query: {query!r}"
            )


def test_bim_queries_contain_only_configured_tokens():
    """
    Stronger form: after removing every token the ICP config contributes,
    nothing but separators should remain.
    """
    bim = _icp("bimwave")
    config = _config_from_icp(bim)

    random.seed(99)
    for query in generate_search_queries(config, count=200):
        remainder = _strip_known_tokens(query, config)
        assert remainder == "", (
            f"query {query!r} contains tokens outside the ICP config: {remainder!r}"
        )


@pytest.mark.parametrize("slug", [icp["slug"] for icp in DEFAULT_ICPS])
def test_all_seeded_icps_stay_in_scope(slug):
    """Every seeded ICP, not just BIM, must stay inside its own config."""
    icp = _icp(slug)
    config = _config_from_icp(icp)
    allowed = {i.lower() for i in icp["industries"]}

    random.seed(7)
    for query in generate_search_queries(config, count=120):
        lowered = query.lower()
        hits = [i for i in allowed if i in lowered]
        # Not every query carries an industry (70% chance), but any industry
        # token present must be one of this ICP's own.
        for other in DEFAULT_ICPS:
            if other["slug"] == slug:
                continue
            for foreign_industry in other["industries"]:
                if foreign_industry.lower() in allowed:
                    continue  # shared across ICPs, legitimate
                assert foreign_industry.lower() not in lowered or hits, (
                    f"{slug}: foreign industry {foreign_industry!r} in {query!r}"
                )


# ============================================
# NO-INDUSTRIES BEHAVIOUR
# ============================================

def test_missing_industries_omits_industry_term():
    """An ICP with no industries must produce queries with no industry at all."""
    config = {
        "designations": ["BIM Manager"],
        "countries": ["India"],
        "seniorities": [],
        "custom_query": "",
        "industries": [],
    }

    random.seed(4)
    queries = generate_search_queries(config, count=100)
    assert queries

    for query in queries:
        assert _strip_known_tokens(query, config) == "", (
            f"industry term appeared despite empty industries: {query!r}"
        )
        # Only the designation and country may be present.
        assert query.strip() == '"BIM Manager" India', query


def test_absent_industries_key_behaves_like_empty():
    """A config that omits `industries` entirely must not fall back to a global list."""
    config = {
        "designations": ["CAD Manager"],
        "countries": ["India"],
        "custom_query": "",
    }

    random.seed(5)
    for query in generate_search_queries(config, count=100):
        assert query.strip() == '"CAD Manager" India', query


def test_none_industries_is_tolerated():
    """`industries: None` must not raise and must not add an industry term."""
    config = {
        "designations": ["BIM Lead"],
        "countries": ["India"],
        "industries": None,
    }

    random.seed(6)
    for query in generate_search_queries(config, count=50):
        assert query.strip() == '"BIM Lead" India', query


# ============================================
# STRUCTURAL GUARD
# ============================================

def test_global_industries_list_is_gone():
    """
    The generic module-level INDUSTRIES list was the bug's root cause.
    Reintroducing it should fail loudly rather than silently leak again.
    """
    assert not hasattr(scheduler, "INDUSTRIES"), (
        "scheduler.INDUSTRIES was reintroduced — industry terms must come "
        "from the ICP config only (see icp_config.py)"
    )


def test_scheduler_optimized_is_deleted():
    """The broken, unwired variant must not come back."""
    with pytest.raises(ImportError):
        __import__("leads.scheduler_optimized")
