"""Panelist ID on the Operations traffic list (owner 2026-11-22)."""
from app.services.traffic_service import _panel_param, traffic_filter_query


def test_search_includes_panelist_id():
    q = traffic_filter_query(search="SFW90E")
    assert {"panelId": {"$regex": "SFW90E", "$options": "i"}} in q["$or"]


def test_panel_param_fallback():
    assert _panel_param({"params": {"panel": "SFW12345678"}}) == "SFW12345678"
    assert _panel_param({"params": {"panel": ["SFW1"]}}) == "SFW1"
    assert _panel_param({"params": {"panel": "[%PANEL%]"}}) == ""
    assert _panel_param({"params": {}}) == ""
    assert _panel_param({}) == ""
