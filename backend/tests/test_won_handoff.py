"""
Tests for app/services/won_handoff.py -- the RFQ-won -> Finance + Operations
bridge. crm_service.mark_opportunity_won() activates a CRM-spine project and
invoice, but Finance (finance_db.customers/work_orders/contracts) and
Operations (email_automation.projects) read their own collections, so a won
deal never appeared there without this.
"""
from datetime import datetime

from app.services import won_handoff as wh


class _Col:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self._n = 0

    def _match(self, doc, query):
        for k, v in (query or {}).items():
            if k == "$or":
                if not any(self._match(doc, sub) for sub in v):
                    return False
                continue
            if isinstance(v, dict):
                if "$regex" in v:
                    import re
                    flags = re.IGNORECASE if v.get("$options") == "i" else 0
                    if not re.search(v["$regex"], str(doc.get(k, "")), flags):
                        return False
                    continue
                if "$in" in v:
                    if doc.get(k) not in v["$in"]:
                        return False
                    continue
            elif doc.get(k) != v:
                return False
        return True

    def find_one(self, query=None, sort=None):
        matches = [d for d in self.docs if self._match(d, query or {})]
        if sort:
            key, direction = sort[0]
            matches.sort(key=lambda d: d.get(key, ""), reverse=direction < 0)
        return matches[0] if matches else None

    def find(self, query=None):
        return [d for d in self.docs if self._match(d, query or {})]

    def count_documents(self, query=None):
        return len(self.find(query))

    def insert_one(self, doc):
        self._n += 1
        doc.setdefault("_id", f"id{self._n}")
        self.docs.append(doc)
        class _R:
            inserted_id = doc["_id"]
        return _R()

    def update_one(self, query, update):
        d = self.find_one(query)
        if d is not None:
            d.update(update.get("$set", {}))


class _Client(dict):
    def __getitem__(self, name):
        return dict.__getitem__(self, name)


def _client(accounts=None, contacts=None, customers=None):
    return _Client({
        "finance_db": {"customers": _Col(customers), "work_orders": _Col(), "contracts": _Col()},
        "email_automation": {"projects": _Col()},
        "crm_db": {"accounts": _Col(accounts), "contacts": _Col(contacts),
                  "opportunities": _Col(), "projects": _Col()},
    })


ACC1 = "64b000000000000000000001"
CONT1 = "64b000000000000000000002"


def _opp(**kw):
    base = {"_id": "opp1", "title": "Q4 tracker", "account_id": ACC1, "contact_id": CONT1,
            "amount": 50000, "currency": "USD", "stage": "won", "status": "won",
            "metadata": {"rfq": {"title": "Q4 tracker", "description": "Quarterly brand tracker",
                                "budget": 50000, "currency": "USD"}}}
    base.update(kw)
    return base


def test_creates_customer_work_order_contract_and_ops_project(monkeypatch):
    from bson import ObjectId
    client = _client(accounts=[{"_id": ObjectId(ACC1), "name": "Acme Research"}],
                     contacts=[{"_id": ObjectId(CONT1), "email": "buyer@acme.com"}])
    monkeypatch.setattr(wh, "_mongo", lambda: client)
    tasks = []
    monkeypatch.setattr(wh, "_open_task", lambda title, *a, **k: tasks.append(title))

    result = wh.handoff_won_opportunity(_opp())

    customers = client["finance_db"]["customers"].docs
    work_orders = client["finance_db"]["work_orders"].docs
    contracts = client["finance_db"]["contracts"].docs
    projects = client["email_automation"]["projects"].docs

    assert len(customers) == 1 and customers[0]["name"] == "Acme Research"
    assert customers[0]["customer_number"] == "CUST-00001"
    assert customers[0]["needs_details"] is True
    assert len(work_orders) == 1 and work_orders[0]["amount"] == 50000
    assert work_orders[0]["customer_id"] == str(customers[0]["_id"])
    assert len(contracts) == 1 and contracts[0]["currency"] == "USD"
    assert len(projects) == 1 and projects[0]["projectStatus"] == "live"
    assert projects[0]["customer_id"] == str(customers[0]["_id"])
    assert result["customer_created"] is True
    assert any("billing details" in t for t in tasks)


def test_reuses_an_existing_customer_by_crm_account(monkeypatch):
    from bson import ObjectId
    existing = {"_id": "cust1", "name": "Acme Research", "crm_account_id": ACC1,
               "customer_number": "CUST-00042", "payment_terms": 45}
    client = _client(accounts=[{"_id": ObjectId(ACC1), "name": "Acme Research"}],
                     contacts=[{"_id": ObjectId(CONT1), "email": "buyer@acme.com"}],
                     customers=[existing])
    monkeypatch.setattr(wh, "_mongo", lambda: client)
    monkeypatch.setattr(wh, "_open_task", lambda *a, **k: None)

    result = wh.handoff_won_opportunity(_opp())

    assert len(client["finance_db"]["customers"].docs) == 1  # no duplicate
    assert result["customer_created"] is False
    assert result["customer_number"] == "CUST-00042"


def test_is_idempotent_per_opportunity(monkeypatch):
    from bson import ObjectId
    client = _client(accounts=[{"_id": ObjectId(ACC1), "name": "Acme Research"}],
                     contacts=[{"_id": ObjectId(CONT1), "email": "buyer@acme.com"}])
    monkeypatch.setattr(wh, "_mongo", lambda: client)
    monkeypatch.setattr(wh, "_open_task", lambda *a, **k: None)

    wh.handoff_won_opportunity(_opp())
    result2 = wh.handoff_won_opportunity(_opp())

    assert len(client["finance_db"]["work_orders"].docs) == 1
    assert "skipped" in result2


def test_never_raises_even_if_the_db_layer_breaks(monkeypatch):
    def _boom():
        raise RuntimeError("mongo is down")
    monkeypatch.setattr(wh, "_mongo", _boom)
    result = wh.handoff_won_opportunity(_opp())
    assert "error" in result
