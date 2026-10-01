"""Search results the model never reached: only new profiles go to the model."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from leads import backlog_drain

NOW = datetime(2026, 10, 1, 12)


class _Backlog:
    def __init__(self, docs):
        self.docs = docs

    def find_one_and_update(self, q, u, sort=None):
        for d in self.docs:
            if d["status"] == "pending":
                d.update(u["$set"])
                return d
        return None

    def find_one(self, q, p=None):
        return next((d for d in self.docs if d["_id"] == q["_id"]), None)

    def update_one(self, q, u):
        for d in self.docs:
            if d["_id"] == q["_id"]:
                d.update(u["$set"])


class _Cur(list):
    pass


class _Leads:
    def find(self, q, p=None):
        return [{"linkedin_url": "https://www.linkedin.com/in/known-person"}]


class _Jobs:
    def find_one(self, q, p=None):
        return {"config": {"icp_id": "survey_fieldwork"}}


def _r(slug, title="x"):
    return {"title": title, "link": f"https://uk.linkedin.com/in/{slug}", "snippet": "s"}


def test_only_new_profiles_reach_the_model_and_are_imported_with_the_icp():
    batch = {"_id": 1, "status": "pending", "query": "q1", "start": 1, "created_at": NOW,
             "results": [_r("known-person"), _r("phil-g"), _r("phil-g"),
                         {"title": "spam", "link": "https://www.linkedin.com/jobs/x"}]}
    only_known = {"_id": 2, "status": "pending", "query": "q1", "created_at": NOW, "results": [_r("known-person")]}
    db = {"extraction_backlog": _Backlog([batch, only_known]), "leads_enriched": _Leads(), "web_search_jobs": _Jobs()}
    seen = []

    async def fake_extract(results, query, start=1):
        seen.append([r["link"] for r in results])
        return [{"name": "Phil Garthside", "title": "Head of Research", "linkedin_url": results[0]["link"],
                 "company_name": "BVRLA", "invented_field": 1}]
    imported = []
    with patch("leads.ingestion.extract_leads_from_google_results", side_effect=fake_extract), \
         patch("leads.service.import_leads",
               side_effect=lambda leads, icp_segment=None, **k: imported.append((leads, icp_segment))
               or SimpleNamespace(imported=len(leads), duplicates=0)):
        stats = backlog_drain.drain(limit=5, now=NOW, db=db)
    assert seen == [["https://uk.linkedin.com/in/phil-g"]]
    assert imported[0][1] == "survey_fieldwork" and imported[0][0][0].source == "websearch"
    assert stats["imported"] == 1 and stats["nothing_new"] == 1
    assert batch["status"] == "consumed" and only_known["status"] == "consumed"


def test_a_busy_model_puts_the_batch_back_and_stops():
    b1 = {"_id": 1, "status": "pending", "query": "q", "created_at": NOW, "results": [_r("new-1")]}
    b2 = {"_id": 2, "status": "pending", "query": "q", "created_at": NOW, "results": [_r("new-2")]}
    db = {"extraction_backlog": _Backlog([b1, b2]), "leads_enriched": _Leads(), "web_search_jobs": _Jobs()}

    async def busy(results, query, start=1):
        b1["status"] = "pending"  # what stash_unextracted_results does
        return []
    with patch("leads.ingestion.extract_leads_from_google_results", side_effect=busy):
        stats = backlog_drain.drain(limit=5, now=NOW, db=db)
    assert stats["model_busy"] and stats["batches"] == 1 and b2["status"] == "pending"
