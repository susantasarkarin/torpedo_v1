"""
SFW respondent quality score (services/respondent_quality.py) and its wiring:
/api/store project flow (flag-only vs enforce), /surveycomplete speeder check,
client reconciliation rejects, and the per-project quality endpoint.
"""
import asyncio
from datetime import datetime, timedelta

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.traffic as traffic
from services import respondent_quality as q
from session_state import verify_session

_MISSING = object()


def _get(doc, dotted):
    for part in dotted.split("."):
        if not isinstance(doc, dict) or part not in doc:
            return _MISSING
        doc = doc[part]
    return doc


def _matches(doc, flt):
    for key, cond in flt.items():
        if key == "$or":
            if not any(_matches(doc, c) for c in cond):
                return False
            continue
        value = _get(doc, key)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$exists" and (value is not _MISSING) != arg:
                    return False
                if op == "$in" and value not in arg:
                    return False
                if op == "$ne" and value == arg:
                    return False
                if op == "$gte" and (value is _MISSING or value < arg):
                    return False
        elif value != cond:
            return False
    return True


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def limit(self, n):
        return FakeCursor(self.docs[:n])

    def sort(self, *a, **k):
        return self

    async def to_list(self, length=None):
        return self.docs[:length]


class FakeCollection:
    def __init__(self, database):
        self.database = database
        self.docs = []

    async def find_one(self, flt, projection=None):
        return next((dict(d) for d in self.docs if _matches(d, flt)), None)

    def find(self, flt, projection=None):
        return FakeCursor([dict(d) for d in self.docs if _matches(d, flt)])

    async def count_documents(self, flt, limit=None):
        n = sum(1 for d in self.docs if _matches(d, flt))
        return min(n, limit) if limit else n

    async def update_one(self, flt, update, upsert=False, array_filters=None):
        def apply(d):
            for k, v in update.get("$set", {}).items():
                if ".$[" in k:  # "attempts.$[a].outcome" with array_filters [{"a.rid": x}]
                    field, _, rest = k.partition(".$[")
                    name, _, sub = rest.partition("].")
                    cond = {key.split(".", 1)[1]: val for f in (array_filters or []) for key, val in f.items()
                            if key.startswith(name + ".")}
                    for el in d.get(field, []):
                        if _matches(el, cond):
                            el[sub] = v
                elif "." in k and k.split(".")[0] in d and isinstance(d[k.split(".")[0]], dict):
                    d[k.split(".")[0]][k.split(".", 1)[1]] = v
                else:
                    d[k] = v
            for k, v in update.get("$push", {}).items():
                d.setdefault(k, []).append(v)
            for k, v in update.get("$addToSet", {}).items():
                if v not in d.setdefault(k, []):
                    d[k].append(v)
        for d in self.docs:
            if _matches(d, flt):
                apply(d)
                return
        if upsert:
            doc = {**flt, **update.get("$setOnInsert", {})}
            apply(doc)
            self.docs.append(doc)

    async def find_one_and_update(self, flt, update, upsert=False, return_document=False):
        for d in self.docs:
            if _matches(d, flt):
                for k, v in update.get("$inc", {}).items():
                    d[k] = d.get(k, 0) + v
                d.update(update.get("$set", {}))
                return dict(d)
        if upsert:
            doc = {**flt, **update.get("$inc", {}), **update.get("$set", {})}
            self.docs.append(doc)
            return dict(doc)
        return None

    async def insert_one(self, doc):
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)

        class R:
            inserted_id = doc["_id"]
        return R()


class FakeDatabase(dict):
    def __missing__(self, name):
        self[name] = FakeCollection(self)
        return self[name]


@pytest.fixture
def col(monkeypatch):
    for var in ("SFW_SCORE_ENABLED", "SFW_SCORE_ENFORCE", "SFW_BLOCK_BELOW", "SFW_REVIEW_BELOW", "IPQS_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return FakeDatabase()["url_parameters"]


def _rec(col, **fields):
    doc = {"_id": ObjectId(), "surveySource": "PROJECT", "assignedSurveyId": "65806", "status": "INCOMPLETE",
           "createdAt": datetime.utcnow(), "vendorId": "5725", "clientIp": "1.2.3.4",
           "profilingData": {"birthday_year": 1990, "birthday_month": 5, "birthday_day": 4, "gender": "male"},
           **fields}
    col.docs.append(doc)
    return doc


def _score(col, doc, project=None):
    return asyncio.run(q.score_entry(col, doc["_id"], project or {"countryCode": "IN"}))


# --- scoring ---------------------------------------------------------------

def test_clean_first_entry_is_good(col):
    doc = _rec(col, sfwVisitorId="visitor-0001", respondentId="r1", geoIpCountry="IN",
               sfwSignals={"webdriver": False, "headlessUA": False, "languages": 2})
    out = _score(col, doc)
    assert out["sfwScore"] == 100 and out["sfwBand"] == "good" and out["sfwFlags"] == []
    assert col.docs[0]["sfwScore"] == 100  # stored on the record


def test_reentry_after_terminate_with_changed_answers_is_blocked(col):
    _rec(col, sfwVisitorId="visitor-0001", respondentId="r1", status="TERMINATED")
    doc = _rec(col, sfwVisitorId="visitor-0001", respondentId="r2",
               profilingData={"birthday_year": 1985, "birthday_month": 5, "birthday_day": 4, "gender": "male"})
    out = _score(col, doc)
    assert {"reentry", "reentry_after_terminate", "answer_change"} <= set(out["sfwFlags"])
    assert out["sfwScore"] == 100 - 35 - 20 - 30 and out["sfwBand"] == "block"


def test_fbp_and_vendor_rid_are_identity_keys(col):
    _rec(col, adTracking={"fbp": "fb.1.1.111"}, respondentId="a")
    assert "reentry" in _score(col, _rec(col, adTracking={"fbp": "fb.1.1.111"}, respondentId="b"))["sfwFlags"]
    _rec(col, respondentId="same-rid", assignedSurveyId="999")
    assert "reentry" in _score(col, _rec(col, respondentId="same-rid", assignedSurveyId="999"))["sfwFlags"]


def test_other_project_is_not_a_reentry(col):
    _rec(col, sfwVisitorId="visitor-0001", assignedSurveyId="11111", status="TERMINATED")
    out = _score(col, _rec(col, sfwVisitorId="visitor-0001"))
    assert "reentry" not in out["sfwFlags"]


def test_shared_fingerprint_alone_is_only_a_weak_flag(col):
    """Thousands of phones share a fingerprint: same fp, different IP = nothing."""
    _rec(col, deviceFingerprint="fp_x", clientIp="9.9.9.9")
    assert _score(col, _rec(col, deviceFingerprint="fp_x", clientIp="1.1.1.1"))["sfwFlags"] == []
    out = _score(col, _rec(col, deviceFingerprint="fp_x", clientIp="9.9.9.9"))
    assert out["sfwFlags"] == ["device_ip_repeat"] and out["sfwBand"] == "good"


def test_bots_geo_and_velocity(col):
    for _ in range(6):
        _rec(col, clientIp="5.5.5.5", assignedSurveyId="other")
    doc = _rec(col, clientIp="5.5.5.5", geoIpCountry="US", userAgent="HeadlessChrome/120",
               sfwSignals={"webdriver": True, "headlessUA": True, "languages": 0})
    flags = set(_score(col, doc)["sfwFlags"])
    assert {"bot_webdriver", "bot_headless", "bot_no_languages", "geo_mismatch", "ip_velocity"} <= flags


def test_cloudflare_country_wins_and_tor(col):
    # browser says IN, Cloudflare says US -> mismatch against an IN project
    out = _score(col, _rec(col, cfIpCountry="US", geoIpCountry="IN"))
    assert "geo_mismatch" in out["sfwFlags"]
    assert "geo_mismatch" not in _score(col, _rec(col, cfIpCountry="IN", geoIpCountry="US"))["sfwFlags"]
    assert "tor" in _score(col, _rec(col, cfIpTor=True))["sfwFlags"]


def test_prior_client_reject_counts_everywhere(col):
    _rec(col, sfwVisitorId="visitor-0002", assignedSurveyId="111", clientRejected=True)
    out = _score(col, _rec(col, sfwVisitorId="visitor-0002"))
    assert "prior_client_reject" in out["sfwFlags"]


def test_thresholds_from_env(col, monkeypatch):
    monkeypatch.setenv("SFW_BLOCK_BELOW", "80")
    assert q.band_for(70) == "block"
    monkeypatch.setenv("SFW_REVIEW_BELOW", "95")
    assert (q.band_for(79), q.band_for(80), q.band_for(94), q.band_for(95)) == ("block", "review", "review", "good")


def test_ip_intel_flags(col, monkeypatch):
    monkeypatch.setenv("IPQS_API_KEY", "k")
    col.database["ip_intel"].docs.append({"_id": "7.7.7.7", "checkedAt": datetime.utcnow(), "result": {
        "vpn": True, "proxy": True, "tor": False, "connection_type": "Data Center",
        "fraud_score": 90, "recent_abuse": True, "country_code": "SG"}})
    flags = set(_score(col, _rec(col, clientIp="7.7.7.7", geoIpCountry="IN"))["sfwFlags"])
    assert {"vpn_proxy", "datacenter_ip", "ip_high_fraud", "ip_recent_abuse", "geo_mismatch"} <= flags


def test_ip_intel_skipped_without_key_or_over_budget(col, monkeypatch):
    assert asyncio.run(q._ip_intel(col.database, "8.8.8.8")) is None  # no key
    monkeypatch.setenv("IPQS_API_KEY", "k")
    monkeypatch.setenv("IPQS_MONTHLY_LIMIT", "0")
    assert asyncio.run(q._ip_intel(col.database, "8.8.8.8")) is None  # budget spent: no HTTP call


def test_speeder_on_completion(col):
    doc = _rec(col, createdAt=datetime.utcnow() - timedelta(minutes=3), sfwFlags=[])
    out = asyncio.run(q.score_completion(col, doc, {"loi": "15"}))  # 3 min < 15/3
    assert "speeder" in out["sfwFlags"] and out["sfwScore"] == 60
    slow = _rec(col, createdAt=datetime.utcnow() - timedelta(minutes=12), sfwFlags=[])
    assert "speeder" not in asyncio.run(q.score_completion(col, slow, {"loi": "15"}))["sfwFlags"]


def test_parse_reject_lines():
    text = "6ac0aebf4d720f1b25ec43db, straight-lining in grid Q12, and speeding\nad-1\tfailed attention check\n  \nx1 x2 x3\nr9;Duplicate (same IP)"
    assert q.parse_reject_lines(text) == [
        {"id": "6ac0aebf4d720f1b25ec43db", "reason": "straight-lining in grid Q12, and speeding"},
        {"id": "ad-1", "reason": "failed attention check"},
        {"id": "x1", "reason": ""}, {"id": "x2", "reason": ""}, {"id": "x3", "reason": ""},
        {"id": "r9", "reason": "Duplicate (same IP)"},
    ]


def test_client_rejects_are_outcomes_not_score_changes(col):
    a = _rec(col, respondentId="vendor-a", sfwScore=85, sfwBand="good", status="COMPLETE",
             adTracking={"campaign_id": "c1"}, traffic_source="meta")
    b = _rec(col, respondentId="vendor-b", sfwScore=55, sfwBand="review")
    out = asyncio.run(q.apply_client_rejects(
        col, "65806",
        [{"id": str(a["_id"]), "reason": "Straight-lined Q12 grid"}, {"id": "vendor-b", "reason": ""},
         {"id": "nope", "reason": "x"}],
        default_reason="Quality", uploaded_by="ops-user", client="Hansa"))
    assert out["matched"] == 2 and out["unmatched"] == ["nope"]
    # SFW-B untouched: rejects must stay an independent outcome
    assert (a["sfwScore"], a["sfwBand"], b["sfwScore"]) == (85, "good", 55)
    assert a["clientRejected"] and a["clientRejectReason"] == "Straight-lined Q12 grid"
    assert b["clientRejectReason"] == "Quality"  # default only where the line had no reason

    hist = {d["_id"]: d for d in col.database["client_rejects"].docs}
    ra = hist[a["_id"]]
    assert (ra["surveyNo"], ra["client"], ra["vendorId"], ra["sfwBAtReject"], ra["statusAtReject"]) == \
        ("65806", "Hansa", "5725", 85, "COMPLETE")
    assert ra["reasonCategory"] is None and ra["adTracking"] == {"campaign_id": "c1"}
    assert ra["history"][0]["uploadedBy"] == "ops-user"
    batch = col.database["client_reject_batches"].docs[0]
    assert (batch["submitted"], batch["matched"], batch["unmatched"]) == (3, 2, ["nope"])


def test_reupload_keeps_history(col):
    a = _rec(col, respondentId="vendor-a")
    asyncio.run(q.apply_client_rejects(col, "65806", [{"id": "vendor-a", "reason": "first"}]))
    asyncio.run(q.apply_client_rejects(col, "65806", [{"id": "vendor-a", "reason": "second"}]))
    rec = col.database["client_rejects"].docs
    assert len(rec) == 1 and rec[0]["reason"] == "second"
    assert [h["reason"] for h in rec[0]["history"]] == ["first", "second"]
    assert a["clientRejectReason"] == "second"


def test_rates():
    row = q._with_rates({"_id": "5725", "entries": 200, "completes": 40, "terminates": 150, "overquota": 0,
                         "sfwBlocked": 0, "scored": 100, "flagged": 25, "review": 10, "block": 5,
                         "avgSfwB": 88.333, "rejects": 4})
    assert (row["key"], row["completeRate"], row["flagRate"], row["reviewRate"], row["blockRate"],
            row["rejectRate"], row["avgSfwB"]) == ("5725", 0.2, 0.25, 0.1, 0.05, 0.1, 88.3)
    assert q._with_rates({"_id": None, "entries": 0, "completes": 0, "scored": 0, "flagged": 0,
                          "review": 0, "block": 0, "avgSfwB": None, "rejects": 0})["rejectRate"] is None


def test_scored_records_carry_q_and_h_placeholders(col):
    doc = _rec(col, sfwVisitorId="visitor-0003")
    _score(col, doc)
    assert "sfwQ" in col.docs[-1] and col.docs[-1]["sfwQ"] is None and col.docs[-1]["sfwH"] is None


# --- wiring ------------------------------------------------------------------

@pytest.fixture
def app_env(monkeypatch, col):
    database = col.database
    monkeypatch.setattr(traffic, "get_async_url_parameters_collection", lambda: col)
    monkeypatch.setattr(traffic, "url_parameters_collection", object())
    monkeypatch.setattr(traffic, "traffic_service", None)

    async def _project(_pid):
        return {"_id": ObjectId(), "surveyNo": "65806", "liveLink": "https://client.example/s?id=", "countryCode": "IN"}

    async def _client_var(_doc):
        return ""
    monkeypatch.setattr(traffic, "_resolve_live_project_async", _project)
    monkeypatch.setattr(traffic, "_resolve_project_client_variable_async", _client_var)

    app = FastAPI()
    app.include_router(traffic.router)
    app.dependency_overrides[verify_session] = lambda: "test-user"
    return TestClient(app), col, database


def test_store_records_cloudflare_country(app_env, monkeypatch):
    client, col, _ = app_env
    monkeypatch.setenv("SFW_SCORE_ENABLED", "true")
    client.post("/api/store", headers={"CF-IPCountry": "SG"}, json={
        "params": {"api": "false", "pid": "65806", "vid": "5725", "cc": "IN", "rid": "cf1"},
        "clientIp": "1.2.3.4", "sfwVisitorId": "visitor-cf01",
        "birthday_day": 4, "birthday_month": 5, "birthday_year": 1990, "gender": "male"})
    rec = next(d for d in col.docs if d.get("respondentId") == "cf1")
    assert rec["cfIpCountry"] == "SG" and "geo_mismatch" in rec["sfwFlags"]


def _store(client, visitor="visitor-0001", rid="r1"):
    return client.post("/api/store", json={
        "url": "https://torpedo.cogentixresearch.com/takesurvey",
        "params": {"api": "false", "pid": "65806", "vid": "5725", "cc": "IN", "rid": rid},
        "clientIp": "1.2.3.4", "sfwVisitorId": visitor,
        "botSignals": {"webdriver": False, "headlessUA": False, "languages": 2},
        "birthday_day": 4, "birthday_month": 5, "birthday_year": 1990, "gender": "male",
    }).json()


def test_store_flag_only_scores_but_never_blocks(app_env, monkeypatch):
    client, col, _ = app_env
    monkeypatch.setenv("SFW_SCORE_ENABLED", "true")
    col.docs.append({"_id": ObjectId(), "surveySource": "PROJECT", "assignedSurveyId": "65806",
                     "sfwVisitorId": "visitor-0001", "status": "COMPLETE", "createdAt": datetime.utcnow()})

    out = _store(client)

    assert out["allocation_success"] is True  # flag-only: still sent to the client
    rec = next(d for d in col.docs if d.get("respondentId") == "r1")
    assert rec["sfwVisitorId"] == "visitor-0001" and "already_completed" in rec["sfwFlags"]
    assert rec["sfwBand"] == "block" and rec["status"] == "INCOMPLETE"


def test_store_enforce_turns_block_band_away(app_env, monkeypatch):
    client, col, _ = app_env
    monkeypatch.setenv("SFW_SCORE_ENABLED", "true")
    monkeypatch.setenv("SFW_SCORE_ENFORCE", "true")
    col.docs.append({"_id": ObjectId(), "surveySource": "PROJECT", "assignedSurveyId": "65806",
                     "sfwVisitorId": "visitor-0001", "status": "COMPLETE", "createdAt": datetime.utcnow()})

    out = _store(client)

    assert out["allocation_success"] is False and out["entry_link"] == ""
    assert out["allocation_error"] == "No survey available"
    rec = next(d for d in col.docs if d.get("respondentId") == "r1")
    assert rec["status"] == "SFW_BLOCKED"


def test_store_disabled_does_not_score(app_env):
    client, col, _ = app_env
    assert _store(client)["allocation_success"] is True
    rec = next(d for d in col.docs if d.get("respondentId") == "r1")
    assert "sfwScore" not in rec and rec["sfwVisitorId"] == "visitor-0001"  # inputs still stored


def test_quality_endpoint_and_rejects(app_env, monkeypatch):
    client, col, _ = app_env
    monkeypatch.setenv("SFW_SCORE_ENABLED", "true")
    _store(client, visitor="visitor-1111", rid="good-one")
    rec = next(d for d in col.docs if d.get("respondentId") == "good-one")
    rec["params"] = {"pid": "65806", "api": "false"}

    out = client.post("/api/sfw/projects/65806/client-rejects",
                      json={"text": "good-one, Speeder per client QC\nmissing-id"}).json()
    assert out["matched"] == 1 and out["unmatched"] == ["missing-id"]
    assert rec["clientRejected"] is True and rec["clientRejectReason"] == "Speeder per client QC"
    assert rec["sfwBand"] == "good"  # outcome recorded, behaviour score untouched
