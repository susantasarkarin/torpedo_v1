from datetime import datetime

import pytest

from marketing import config, schema

PLAN_SECTION_5 = """web_sites web_visitors web_sessions web_events consents touchpoints attribution_results ga4_daily
gsc_queries_daily gsc_pages_daily seo_audits seo_issues cwv_results keywords keyword_positions content_gaps ad_accounts
ad_campaigns ad_groups ads ad_metrics_daily search_terms offline_conversion_uploads audiences social_accounts social_posts
social_metrics_daily inbox_items whatsapp_optins whatsapp_templates content_items brand_voice experiments
decision_candidates decisions decision_outcomes marketing_kpi_snapshots""".split()


def test_every_plan_collection_registered():
    assert set(PLAN_SECTION_5) <= set(schema.COLLECTIONS)     # marketing_config = config_store section
    assert set(schema.COLLECTIONS) - set(PLAN_SECTION_5) == {"gsc_sitemaps", "gsc_url_index", "marketing_touches", "marketing_eval_cases", "marketing_eval_runs", "lead_form_pending"}


def test_daily_tables_have_date_bu_index():
    for name, (idx, _) in schema.COLLECTIONS.items():
        if name.endswith("_daily") or name in ("cwv_results", "keyword_positions", "search_terms", "marketing_kpi_snapshots"):
            assert any(k == schema.D for k, _ in idx), name


def test_retention_only_on_raw_web():
    assert {n for n, (_, r) in schema.COLLECTIONS.items() if r} == {"web_events", "web_sessions"}
    assert schema.COLLECTIONS["consents"][1] is None and schema.COLLECTIONS["whatsapp_optins"][1] is None


def test_stamp_requires_bu_and_source():
    now = datetime(2026, 10, 25)
    d = schema.stamp({"x": 1}, bu="SFW", source="gsc", now=now)
    assert d == {"x": 1, "bu": "SFW", "source": "gsc", "created_at": now, "updated_at": now}
    with pytest.raises(ValueError):
        schema.stamp({}, bu="ACME", source="gsc")
    with pytest.raises(ValueError):
        schema.stamp({}, bu="SFW", source="")


def test_upsert_ops_keeps_created_at_on_insert_only():
    now = datetime(2026, 10, 25)
    f, u = schema.upsert_ops({"site": "a.com", "date": "2026-10-24", "clicks": 3}, ["site", "date"],
                             bu="BIM", source="gsc", now=now)
    assert f == {"site": "a.com", "date": "2026-10-24"}
    assert "created_at" not in u["$set"] and u["$setOnInsert"] == {"created_at": now}


def test_ensure_indexes_dry_run_touches_nothing():
    rep = schema.ensure_indexes(client=None)
    assert rep["collections"] == len(schema.COLLECTIONS) and rep["indexes_planned"] > 60 and rep["created"] == []


def test_everything_starts_l1_and_shadow():
    assert config.DEFAULTS["mode"] == "shadow"
    assert set(config.DEFAULTS["autonomy"].values()) == {"L1"}
    assert len(config.DECISION_TYPES) == 14


def test_l3_capped_for_budget_bids_client_facing():
    cfg = {"autonomy": {"D1": "L3", "D3": "L3", "D4": "L3", "D2": "bogus"}}
    assert config.autonomy(cfg, "D1") == "L2" and config.autonomy(cfg, "D3") == "L2"
    assert config.autonomy(cfg, "D4") == "L3"
    assert config.autonomy(cfg, "D2") == "L1" and config.autonomy(cfg, "D9") == "L1"


def test_kill_switch_global_or_bu():
    assert config.killed({"kill_switch": {"global": True}}, "SFW")
    assert config.killed({"kill_switch": {"BIM": True}}, "BIM")
    assert not config.killed({"kill_switch": {"BIM": True}}, "SFW")


def test_registered_in_config_store():
    from platform_core import config_store
    assert config_store.SECTIONS["marketing"]()["budget"]["max_daily_change_pct"] == 20
