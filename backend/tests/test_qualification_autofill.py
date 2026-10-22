"""Qualifications filled from the RFQ email: empty fields only, never after a manual save."""
import asyncio

from bson import ObjectId

from services import qualification_autofill as qa
from services import rfq_targeting

FOUND = {"qualification": {"ageMin": 18, "ageMax": 60, "genders": ["f"], "nccs": ["A1", "A2", "A3"], "cities": "Delhi, Mumbai"},
         "loi": 10, "ir": 40}


def test_fills_empty_fields_only():
    project = {"countryCode": "IN", "loi": "15", "qualification": {"enabled": True, "genders": ["m"], "cities": ""}}
    sets = qa.merge(project, FOUND)
    q = sets["qualification"]
    assert q["genders"] == ["m"]                               # set by the team: kept
    assert q["cities"] == "Delhi, Mumbai" and q["nccs"] == ["A1", "A2", "A3"]
    assert q["ageRanges"] == [{"min": 18, "max": 60}] and q["enabled"] is True
    assert "loi" not in sets and sets["clientIR"] == "40"      # LOI already there


def test_existing_age_is_kept_and_nothing_to_do():
    project = {"countryCode": "IN", "loi": "10", "clientIR": "40",
               "qualification": {"enabled": True, "ageMin": 25, "genders": ["f"], "nccs": ["B1"], "cities": "Pune"}}
    assert qa.merge(project, FOUND) == {}


def test_nccs_not_filled_outside_india():
    sets = qa.merge({"countryCode": "UK"}, FOUND)
    assert "nccs" not in sets["qualification"]


class _Col:
    def __init__(self):
        self.updates, self.inserts = [], []

    async def update_one(self, flt, upd):
        self.updates.append((flt, upd))

    async def insert_one(self, doc):
        self.inserts.append(doc)


class _Db(dict):
    def __missing__(self, key):
        self[key] = _Col()
        return self[key]


class _Client(dict):
    def __missing__(self, key):
        self[key] = _Db()
        return self[key]


def test_manual_projects_are_never_touched(monkeypatch):
    async def brief(_col, _p):
        return {"subject": "RFQ_X", "text": "Target Group:\n* Women only\n* Aged 18-60\nThanks"}
    monkeypatch.setattr(rfq_targeting, "find_brief", brief)
    client = _Client()
    assert asyncio.run(qa.fill({"_id": ObjectId(), "qualificationManual": True}, client)) is None
    assert client["email_automation"]["projects"].updates == []


def test_fill_writes_backup_and_source(monkeypatch):
    async def brief(_col, _p):
        return {"subject": "RFQ_X", "text": "Target Group:\n* Women only\n* Aged 18-60 years\nThanks"}
    monkeypatch.setattr(rfq_targeting, "find_brief", brief)
    client = _Client()
    pid = ObjectId()
    sets = asyncio.run(qa.fill({"_id": pid, "countryCode": "IN", "qualification": {}}, client))
    assert sets["qualification"]["genders"] == ["f"] and sets["qualificationSource"]["subject"] == "RFQ_X"
    flt, upd = client["email_automation"]["projects"].updates[0]
    assert flt == {"_id": pid, "qualificationManual": {"$ne": True}}       # a manual save in between wins
    assert client["email_automation"]["projects_qualification_backup_auto"].inserts[0]["projectId"] == pid


def test_no_email_no_change(monkeypatch):
    async def brief(_col, _p):
        return None
    monkeypatch.setattr(rfq_targeting, "find_brief", brief)
    client = _Client()
    assert asyncio.run(qa.fill({"_id": ObjectId(), "qualification": {}}, client)) is None
