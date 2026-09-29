"""Contracts on a win: yearly per financial year for clients on a yearly
contract, otherwise one per project (owner, 2026-09-29)."""
from datetime import datetime

from app.services import won_handoff as wh


class _Contracts:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.added = []

    def find_one(self, q, *a, **k):
        if "contract_number" in q:   # _next_number
            return None
        for d in self.docs:
            if (d.get("customer_id") == q.get("customer_id") and d.get("contract_type") == q.get("contract_type")
                    and d["start_date"] <= q["start_date"]["$lte"] and d["end_date"] >= q["end_date"]["$gte"]):
                return d
        return None

    def count_documents(self, q):
        return len(self.docs)

    def insert_one(self, doc):
        doc["_id"] = f"c{len(self.docs) + 1}"
        self.docs.append(doc)

        class R:
            inserted_id = doc["_id"]
        return R()

    def update_one(self, q, u):
        self.added.append((q, u))


def test_indian_financial_year():
    assert wh.financial_year(datetime(2026, 9, 29)) == (datetime(2026, 4, 1), datetime(2027, 3, 31, 23, 59, 59))
    assert wh.financial_year(datetime(2026, 2, 1))[0] == datetime(2025, 4, 1)


def test_yearly_client_projects_share_one_contract_per_year():
    fin = {"contracts": _Contracts()}
    base = {"customer_id": "cust1", "customer_name": "Hansa", "status": "draft"}
    yearly = {"contract_type": "yearly"}
    cid1, _, created1 = wh._contract_for(fin, yearly, "opp1", datetime(2026, 5, 1), dict(base), False)
    cid2, _, created2 = wh._contract_for(fin, yearly, "opp2", datetime(2026, 11, 1), dict(base), False)
    cid3, _, created3 = wh._contract_for(fin, yearly, "opp3", datetime(2027, 5, 1), dict(base), False)
    assert created1 and not created2 and created3
    assert cid1 == cid2 != cid3


def test_other_clients_get_a_contract_per_project():
    fin = {"contracts": _Contracts()}
    base = {"customer_id": "cust2", "status": "draft"}
    a = wh._contract_for(fin, {}, "opp1", datetime(2026, 5, 1), dict(base), False)
    b = wh._contract_for(fin, {}, "opp2", datetime(2026, 5, 2), dict(base), True)
    assert a[0] != b[0] and a[2] and b[2]
    assert fin["contracts"].docs[1]["status"] == "completed"   # historical
