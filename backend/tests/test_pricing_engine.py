"""Rules that decide a price (CRM plan 3.5): band selection and widening, the
weighted-median definition, the 90-day completes window, markup and margin floor."""
from datetime import datetime, timedelta

from pricing import engine as e

NOW = datetime(2026, 10, 24)


def row(cpi, completes=100, loi=15, ir=25, country="IN", days_ago=10):
    return {"cpi": cpi, "completes": completes, "loi": loi, "ir": ir, "country": country,
            "activated_at": NOW - timedelta(days=days_ago)}


def test_weighted_median_is_first_cpi_reaching_half_the_weight():
    rows = [(row(1.0), 10), (row(2.0), 10), (row(3.0), 80)]
    assert e.weighted_median(rows) == 3.0          # 10+10 < 50, 10+10+80 >= 50
    assert e.weighted_median([(row(1.0), 50), (row(9.0), 50)]) == 1.0   # exactly 50% counts


def test_weighted_median_empty_or_zero_weight_is_none():
    assert e.weighted_median([]) is None
    assert e.weighted_median([(row(1.0), 0)]) is None


def test_completes_window_drops_old_and_undated_rows():
    old, new, undated = row(5.0, days_ago=120), row(1.0, days_ago=5), dict(row(9.0), activated_at=None)
    kept = e.weight_completes([old, new, undated], NOW)
    assert [r["cpi"] for r, _ in kept] == [1.0]


def test_recency_weights_newer_rows_more():
    w = dict((r["cpi"], x) for r, x in e.weight_recency([row(1.0, days_ago=0), row(2.0, days_ago=30)], NOW))
    assert w[1.0] == 1.0 and abs(w[2.0] - 0.5) < 1e-9


def test_exact_country_only():
    picked, tr = e.select_rows([row(1, country="US")] * 10, country="IN", loi=15, ir=25)
    assert picked == [] and tr["enough_rows"] is False


def test_bands_widen_one_step_until_min_rows():
    rows = [row(1.0, loi=15, ir=25)] * 2 + [row(2.0, loi=12, ir=35)] * 4   # neighbouring bands
    picked, tr = e.select_rows(rows, country="IN", loi=15, ir=25)
    assert tr["widened_steps"] == 1 and len(picked) == 6


def test_price_line_applies_bu_markup_and_passes_floor():
    rows = [row(2.0)] * 6
    p = e.price_line(rows, bu="SFW", country="IN", loi=15, ir=25, now=NOW)
    assert p["weighted_median_usd"] == 2.0 and p["client_cpi_usd"] == 3.0 and p["review"] is False
    p = e.price_line(rows, bu="COGENTIX", country="IN", loi=15, ir=25, now=NOW)
    assert p["client_cpi_usd"] == 3.2


def test_client_markup_overrides_bu_default():
    p = e.price_line([row(2.0)] * 6, bu="SFW", country="IN", loi=15, ir=25, now=NOW, client_markup=1.2)
    assert p["client_cpi_usd"] == 2.4
    assert p["review"] is True and "below floor" in p["review_reasons"][0]   # margin 17% < 30%


def test_vendor_cost_below_floor_goes_to_review():
    p = e.price_line([row(2.0)] * 6, bu="SFW", country="IN", loi=15, ir=25, now=NOW, vendor_cost=2.5)
    assert p["review"] is True


def test_too_few_rows_goes_to_review_without_a_price():
    p = e.price_line([row(2.0)] * 2, bu="SFW", country="IN", loi=15, ir=25, now=NOW)
    assert p["client_cpi_usd"] is None and p["review"] is True
