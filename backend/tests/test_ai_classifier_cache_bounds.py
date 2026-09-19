"""
Covers a 2026-09-19 fix to leads/ai_classifier.py: _classification_cache was
an unbounded dict with no eviction -- every distinct name+title pair
classified over the process's lifetime stayed in memory forever. Identified
(alongside email_sync/router.py's _background_tasks) as a concrete cause of
the API's observed memory growth (535MB -> 1GB+ over ~20h).

Fixed with a bounded LRU: same get/set interface, capped size, oldest-entry
eviction.
"""
from unittest.mock import patch

from leads import ai_classifier as m
from leads.models import LeadRaw


def _lead(name: str, title: str = "VP Sales") -> LeadRaw:
    return LeadRaw(name=name, title=title, linkedin_url=f"https://linkedin.com/in/{name}")


def test_cache_miss_returns_none():
    assert m.get_cached_classification(_lead("nobody-cached")) is None


def test_cache_hit_returns_stored_value():
    lead = _lead("Jane Doe")
    m.cache_classification(lead, "fake-result-object")
    assert m.get_cached_classification(lead) == "fake-result-object"


def test_cache_is_bounded_and_evicts_oldest():
    with patch.object(m, "_CLASSIFICATION_CACHE_MAX_SIZE", 3):
        m._classification_cache.clear()
        leads = [_lead(f"Person {i}") for i in range(5)]
        for lead in leads:
            m.cache_classification(lead, f"result-{lead.name}")

        assert len(m._classification_cache) == 3
        # The two oldest (Person 0, Person 1) must have been evicted.
        assert m.get_cached_classification(leads[0]) is None
        assert m.get_cached_classification(leads[1]) is None
        # The three most recent survive.
        assert m.get_cached_classification(leads[2]) == "result-Person 2"
        assert m.get_cached_classification(leads[3]) == "result-Person 3"
        assert m.get_cached_classification(leads[4]) == "result-Person 4"


def test_reading_a_cached_entry_protects_it_from_eviction():
    """LRU, not FIFO -- a re-read entry should survive over one that was
    never touched again, even if it was inserted earlier."""
    with patch.object(m, "_CLASSIFICATION_CACHE_MAX_SIZE", 2):
        m._classification_cache.clear()
        a, b, c = _lead("A"), _lead("B"), _lead("C")
        m.cache_classification(a, "result-A")
        m.cache_classification(b, "result-B")
        m.get_cached_classification(a)  # touch A -- B is now the oldest
        m.cache_classification(c, "result-C")  # forces an eviction

        assert m.get_cached_classification(b) is None  # evicted
        assert m.get_cached_classification(a) == "result-A"
        assert m.get_cached_classification(c) == "result-C"
