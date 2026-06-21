"""
Integration tests for state.py — uses a temporary SQLite file.
No network calls.
"""

import os
import tempfile
import pytest

# Point at a temp DB before state module initialises
_tmp = tempfile.mktemp(suffix=".db")
os.environ["LEAD_GEN_DB_PATH"] = _tmp

import importlib
import backend.lead_gen_mcp.state as st
importlib.reload(st)   # re-init with the temp path


def teardown_module(_):
    try:
        os.unlink(_tmp)
    except OSError:
        pass


# ---------------------------------------------------------------------------

def test_upsert_and_get_icp():
    st.upsert_icp(
        icp_id="test_icp",
        name="Test ICP",
        target_titles=["CTO", "VP Engineering"],
        target_industries=["SaaS", "Fintech"],
        target_geos=["India"],
    )
    icp = st.get_icp("test_icp")
    assert icp is not None
    assert icp["name"] == "Test ICP"
    assert "CTO" in icp["target_titles"]


def test_upsert_icp_is_idempotent():
    st.upsert_icp("test_icp", "Updated Name", ["CEO"], ["EdTech"], ["UK"])
    icp = st.get_icp("test_icp")
    assert icp["name"] == "Updated Name"
    assert "CEO" in icp["target_titles"]


def test_profiles_seen_roundtrip():
    url = "https://linkedin.com/in/test-profile-abc"
    assert not st.is_profile_seen(url)
    assert st.mark_profile_seen(url, "test_icp", "q1") is True
    assert st.is_profile_seen(url)
    # Second mark should return False (already seen)
    assert st.mark_profile_seen(url, "test_icp", "q2") is False


def test_profiles_seen_count():
    count_before = st.profiles_seen_count("test_icp")
    st.mark_profile_seen("https://linkedin.com/in/fresh-one", "test_icp", "q")
    count_after = st.profiles_seen_count("test_icp")
    assert count_after == count_before + 1


def test_upsert_lead():
    eid = st.upsert_lead({
        "profile_url": "https://linkedin.com/in/lead-x",
        "icp_id": "test_icp",
        "name": "Lead X",
        "title": "CTO",
        "company": "AcmeCo",
        "status": "scored",
    })
    assert len(eid) == 64   # SHA-256 hex


def test_log_query_and_count():
    before = st.queries_run_count("test_icp")
    st.log_query(
        icp_id="test_icp",
        query_text='site:linkedin.com/in/ "CTO" India',
        dimension_cell="cto|saas|india",
        result_count=8,
        novel_count=5,
        icp_passing=4,
        enriched_count=2,
        pushed_count=1,
    )
    after = st.queries_run_count("test_icp")
    assert after == before + 1


def test_coverage_exhaustion():
    cell = "vp_sales|fintech|india"
    for i in range(4):
        st.record_coverage_attempt("test_icp", cell, novel_count=0)
    exhausted = st.get_exhausted_cells("test_icp")
    assert cell in exhausted


def test_coverage_not_exhausted_when_yield_ok():
    cell = "cto|saas|uk"
    for _ in range(5):
        st.record_coverage_attempt("test_icp", cell, novel_count=3)
    exhausted = st.get_exhausted_cells("test_icp")
    assert cell not in exhausted


def test_synonyms_roundtrip():
    st.add_synonym("test_icp", "title", "VP Sales", "Chief Revenue Officer")
    synonyms = st.get_synonyms("test_icp", dimension="title")
    found = [s for s in synonyms if s["synonym"] == "Chief Revenue Officer"]
    assert len(found) == 1


def test_trigger_ingest_and_pop():
    st.ingest_trigger("AcmeCorp", "funding", "Series B raise", icp_id="test_icp")
    pending = st.pop_pending_triggers(icp_id="test_icp", limit=5)
    companies = [t["company_name"] for t in pending]
    assert "AcmeCorp" in companies
    # Second pop should not return already-injected triggers
    pending2 = st.pop_pending_triggers(icp_id="test_icp", limit=5)
    assert "AcmeCorp" not in [t["company_name"] for t in pending2]


def test_get_lead_counts():
    st.upsert_lead({
        "profile_url": "https://linkedin.com/in/lead-y",
        "icp_id": "test_icp",
        "status": "pushed",
    })
    counts = st.get_lead_counts("test_icp")
    assert counts.get("pushed", 0) >= 1
