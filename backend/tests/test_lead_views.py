"""AI Database, Leads and Contacts are disjoint: a record is on exactly one page."""

import pytest

from leads import service
from leads.models import LeadFilterParams

RECORDS = [
    {"_id": 1, "name": "n1", "source": "web_search"},                                   # AI Database
    {"_id": 2, "name": "n2", "source": "gmail", "stage": "already_contacted"},          # Leads
    {"_id": 3, "name": "n3", "source": "web_search", "outreach_replied_at": 1},         # Leads (replied)
    {"_id": 4, "name": "n4", "source": "gmail", "stage": "discovery_call"},             # Contacts
    {"_id": 5, "name": "n5", "source": "csv", "stage": "negotiation"},                  # Contacts
    {"_id": 6, "name": "n6", "source": "gmail_reply"},                                  # Leads
    {"_id": 7, "name": "n7", "source": "gmail", "transferred_to_vendor_leads": True},   # Vendor — none
]

_MISSING = object()


def _match(doc, query):
    """The subset of Mongo query semantics get_leads uses."""
    for key, cond in query.items():
        if key == "$and":
            if not all(_match(doc, q) for q in cond):
                return False
        elif key == "$or":
            if not any(_match(doc, q) for q in cond):
                return False
        elif key == "$nor":
            if any(_match(doc, q) for q in cond):
                return False
        else:
            value = doc.get(key, _MISSING)
            if isinstance(cond, dict):
                for op, arg in cond.items():
                    v = None if value is _MISSING else value
                    if op == "$in" and v not in arg:
                        return False
                    if op == "$nin" and v in arg:
                        return False
                    if op == "$ne" and v == arg:
                        return False
                    if op == "$exists" and (value is not _MISSING) != arg:
                        return False
            elif value != cond:
                return False
    return True


class _Cursor(list):
    def sort(self, keys, direction=None):
        if direction is not None:
            keys = [(keys, direction)]
        for field, direction in reversed(keys):
            super().sort(key=lambda d: (d.get(field) is None, d.get(field)), reverse=direction < 0)
        return self

    def allow_disk_use(self, _):
        return self

    def skip(self, n):
        return _Cursor(self[n:])

    def limit(self, n):
        return _Cursor(self[:n])


class _Collection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query):
        return _Cursor(dict(d) for d in self.docs if _match(d, query))

    def count_documents(self, query):
        return sum(1 for d in self.docs if _match(d, query))

    def aggregate(self, pipeline, allowDiskUse=False):
        """Only the sort pipeline get_leads builds: match, blank flag, sort, page."""
        stages = {next(iter(st)): st[next(iter(st))] for st in pipeline}
        rows = [dict(d) for d in self.docs if _match(d, stages["$match"])]
        field = [k for k in stages["$sort"] if k not in ("_blank", "_id")][0]
        reverse = stages["$sort"][field] < 0
        filled = [r for r in rows if r.get(field) not in (None, "", "Unknown")]
        blank = [r for r in rows if r.get(field) in (None, "", "Unknown")]
        filled.sort(key=lambda r: r[field], reverse=reverse)
        out = filled + blank
        return out[stages["$skip"]:stages["$skip"] + stages["$limit"]]


@pytest.fixture(autouse=True)
def coll(monkeypatch):
    monkeypatch.setattr(service, "leads_enriched_collection", _Collection(RECORDS))


def ids(**kw):
    leads, total = service.get_leads(LeadFilterParams(limit=50, **kw))
    assert total == len(leads)
    return {l["_id"] for l in leads}


def test_views_partition_the_records():
    ai, leads, contacts = ids(view="ai_database"), ids(view="leads"), ids(view="contacts")
    assert ai == {"1"}
    assert leads == {"2", "3", "6"}
    assert contacts == {"4", "5"}
    assert not (ai & leads) and not (ai & contacts) and not (leads & contacts)


def test_qualified_only_is_the_leads_view():
    assert ids(qualified_only=True) == {"2", "3", "6"}


def test_a_specific_contact_stage_stays_inside_contacts():
    assert ids(view="contacts", lead_stage="negotiation") == {"5"}


def test_sort_by_column():
    asc, _ = service.get_leads(LeadFilterParams(view="leads", sort_by="lead", sort_order="asc", limit=50))
    desc, _ = service.get_leads(LeadFilterParams(view="leads", sort_by="lead", sort_order="desc", limit=50))
    assert [l["name"] for l in asc] == ["n2", "n3", "n6"]
    assert [l["name"] for l in desc] == ["n6", "n3", "n2"]


def test_blanks_sort_last_both_ways(monkeypatch):
    docs = [{"_id": i, "source": "gmail", "company_name": c}
            for i, c in enumerate(["", "Beta", None, "Acme"], start=1)]
    monkeypatch.setattr(service, "leads_enriched_collection", _Collection(docs))
    asc, _ = service.get_leads(LeadFilterParams(view="leads", sort_by="company", sort_order="asc", limit=50))
    desc, _ = service.get_leads(LeadFilterParams(view="leads", sort_by="company", sort_order="desc", limit=50))
    assert [l.get("company_name") for l in asc][:2] == ["Acme", "Beta"]
    assert [l.get("company_name") for l in desc][:2] == ["Beta", "Acme"]


def test_unknown_sort_key_falls_back_safely():
    assert ids(view="leads", sort_by="$where") == {"2", "3", "6"}
