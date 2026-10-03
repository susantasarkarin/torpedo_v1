"""
/surveycomplete -> /adpixel (React thank-you page) -> GET /api/adpixel.

The API returns a pixel only for: well-formed RID -> existing COMPLETE record ->
ad traffic_source with an enabled platform -> not already fired. Everything
else gets {"pixel": null}, never a reason. Vendor (non-ad) traffic keeps its redirect.
"""
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.traffic as traffic
from services.ad_tracking import derive_traffic_source, extract_ad_tracking

PIXEL_ID = "192934514575015"


_MISSING = object()


def _get(doc, dotted):
    for part in dotted.split("."):
        if not isinstance(doc, dict) or part not in doc:
            return _MISSING
        doc = doc[part]
    return doc


def _matches(doc, flt):
    for key, cond in flt.items():
        value = _get(doc, key)
        if isinstance(cond, dict) and "$exists" in cond:
            if (value is not _MISSING) != cond["$exists"]:
                return False
        elif isinstance(cond, dict) and "$in" in cond:
            if value not in cond["$in"]:
                return False
        elif value != cond:
            return False
    return True


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def limit(self, n):
        return FakeCursor(self.docs[:n])

    async def to_list(self, length=None):
        return self.docs[:length]


class FakeCollection:
    def __init__(self, database, docs=None):
        self.database = database
        self.docs = docs if docs is not None else []

    async def find_one(self, flt, projection=None):
        return next((dict(d) for d in self.docs if _matches(d, flt)), None)

    def find(self, flt, projection=None):
        return FakeCursor([dict(d) for d in self.docs if _matches(d, flt)])

    async def update_one(self, flt, update):
        for d in self.docs:
            if _matches(d, flt):
                d.update(update.get("$set", {}))
                return
        return

    async def find_one_and_update(self, flt, update):
        for d in self.docs:
            if _matches(d, flt):
                before = dict(d)
                d.update(update.get("$set", {}))
                return before
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))


class FakeDatabase(dict):
    def __missing__(self, name):
        self[name] = FakeCollection(self)
        return self[name]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("META_PIXEL_ID", PIXEL_ID)
    monkeypatch.delenv("META_PIXEL_ENABLED", raising=False)
    monkeypatch.delenv("AD_PIXEL_FIRE_ON_TERMINATE", raising=False)
    database = FakeDatabase()
    url_params = database["url_parameters"]
    monkeypatch.setattr(traffic, "get_async_url_parameters_collection", lambda: url_params)
    vendors = database["vendors"]
    monkeypatch.setattr(traffic, "get_async_vendors_collection", lambda: vendors)

    app = FastAPI()
    app.include_router(traffic.router)
    client = TestClient(app)
    return client, url_params, database


def _add_record(url_params, **fields):
    rid = ObjectId()
    url_params.docs.append({"_id": rid, "status": "INCOMPLETE", "assignedSurveyId": "SV-42", **fields})
    return str(rid)


def _complete(client, rid):
    return client.get("/surveycomplete", params={"rid": rid}, follow_redirects=False)


def _pixel(client, rid):
    resp = client.get("/api/adpixel", params={"rid": rid})
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    return resp.json()["pixel"]


def _complete_and_land(client, rid):
    """Client survey -> /surveycomplete -> 302 /adpixel?rid= -> page asks /api/adpixel."""
    resp = _complete(client, rid)
    assert resp.status_code == 302
    assert resp.headers["location"] == f"/adpixel?rid={rid}"
    return _pixel(client, rid)


def test_valid_first_completion_returns_meta_pixel(env):
    client, url_params, database = env
    rid = _add_record(url_params, traffic_source="meta")

    pixel = _complete_and_land(client, rid)

    assert pixel == {"platform": "meta", "pixel_id": PIXEL_ID, "survey_id": "SV-42",
                     "event_id": f"complete_{rid}"}
    record = url_params.docs[0]
    assert record["status"] == "COMPLETE"  # existing completion logic still ran
    assert record["ad_pixel_fired_at"] is not None
    fires = database["ad_pixel_fires"].docs
    assert len(fires) == 1 and fires[0]["rid"] == rid and fires[0]["platform"] == "meta"


def test_refresh_and_reused_link_do_not_fire_twice(env):
    client, url_params, database = env
    rid = _add_record(url_params, traffic_source="meta")

    assert _complete_and_land(client, rid) is not None
    assert _pixel(client, rid) is None              # refresh
    assert _complete_and_land(client, rid) is None  # reused completion link
    assert len(database["ad_pixel_fires"].docs) == 1


def test_unknown_rid(env):
    client, _, database = env
    unknown = str(ObjectId())

    resp = _complete(client, unknown)
    assert resp.status_code == 302 and resp.headers["location"] == "/adpixel"  # page, no rid
    assert _pixel(client, unknown) is None
    assert database["ad_pixel_fires"].docs == []


def test_adpixel_before_completion_fires_nothing(env):
    """/api/adpixel is public: a mid-survey RID must not fire."""
    client, url_params, _ = env
    rid = _add_record(url_params, traffic_source="meta")  # INCOMPLETE

    assert _pixel(client, rid) is None
    assert "ad_pixel_fired_at" not in url_params.docs[0]
    assert _complete_and_land(client, rid) is not None  # the real completion still fires


def test_non_ad_traffic_keeps_vendor_flow_and_no_pixel(env):
    client, url_params, _ = env
    rid = _add_record(url_params, traffic_source="direct")

    resp = _complete(client, rid)

    assert resp.status_code in (302, 307)
    assert resp.headers["location"].endswith("/thankyou")  # unchanged fallback
    assert _pixel(client, rid) is None
    assert "ad_pixel_fired_at" not in url_params.docs[0]


def test_ad_traffic_with_disabled_platform_gets_no_pixel(env):
    client, url_params, _ = env
    rid = _add_record(url_params, traffic_source="tiktok")  # present in config, disabled

    assert _complete_and_land(client, rid) is None
    assert "ad_pixel_fired_at" not in url_params.docs[0]


def test_meta_disabled_by_env(env, monkeypatch):
    client, url_params, _ = env
    monkeypatch.setenv("META_PIXEL_ENABLED", "false")
    rid = _add_record(url_params, traffic_source="meta")

    assert _complete_and_land(client, rid) is None


@pytest.mark.parametrize("bad_rid", [
    "not-an-id",
    "<script>alert(1)</script>",
    "'); fbq('track','Purchase'); ('",
    "a" * 25,
    "",
])
def test_malformed_rid_rejected_safely(env, bad_rid):
    client, url_params, database = env
    _add_record(url_params, traffic_source="meta")

    resp = _complete(client, bad_rid)
    assert resp.status_code == 302 and resp.headers["location"] == "/adpixel"  # rid never echoed
    assert client.get("/api/adpixel", params={"rid": bad_rid}).json() == {"pixel": None}
    assert database["ad_pixel_fires"].docs == []


def test_terminate_fires_only_with_testing_switch(env, monkeypatch):
    client, url_params, _ = env
    rid = _add_record(url_params, traffic_source="meta")
    client.get("/surveyterminate", params={"rid": rid}, follow_redirects=False)

    assert _pixel(client, rid) is None  # default: terminates never fire
    monkeypatch.setenv("AD_PIXEL_FIRE_ON_TERMINATE", "true")
    assert _pixel(client, rid)["event_id"] == f"complete_{rid}"
    assert _pixel(client, rid) is None  # still once only


def test_terminate_unchanged_for_ad_traffic(env):
    client, url_params, _ = env
    rid = _add_record(url_params, traffic_source="meta")

    resp = client.get("/surveyterminate", params={"rid": rid}, follow_redirects=False)

    assert resp.status_code in (302, 307)
    assert "adpixel" not in resp.headers["location"]
    assert "ad_pixel_fired_at" not in url_params.docs[0]


# --- /adpixel reached with the ad-side identifier ----------------------------

def test_by_ad_rid_fires_once_with_that_event_id(env):
    """rid on /adpixel = the id that came in on the ad URL (respondentId)."""
    client, url_params, database = env
    sfwid = _add_record(url_params, traffic_source="meta", respondentId="FB-7781234")
    _complete(client, sfwid)  # client survey reports completion with our SFWID

    assert _pixel(client, "FB-7781234")["event_id"] == "complete_FB-7781234"
    assert _pixel(client, "FB-7781234") is None
    assert _pixel(client, sfwid) is None  # same person, other id
    assert [f["record_id"] for f in database["ad_pixel_fires"].docs] == [sfwid]


def test_facebook_ads_vendor_complete_url_routes_to_adpixel(env):
    """Operations > Vendors > facebook_ads: complete URL = .../adpixel?rid="""
    client, url_params, database = env
    database["vendors"].docs.append({
        "vid": "77", "vendorName": "facebook_ads", "vendorVariable": "rid",
        "completeRD": ["https://torpedo.cogentixresearch.com/adpixel?rid="],
    })
    sfwid = _add_record(url_params, traffic_source="meta", vendorId="77", respondentId="ad-1b2c3d4e")

    resp = _complete(client, sfwid)

    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "https://torpedo.cogentixresearch.com/adpixel?rid=ad-1b2c3d4e"
    assert _pixel(client, "ad-1b2c3d4e")["event_id"] == "complete_ad-1b2c3d4e"


def test_by_fbclid(env):
    client, url_params, _ = env
    fbclid = "IwAR2xYz_abc-123"
    sfwid = _add_record(url_params, traffic_source="meta", adTracking={"fbclid": fbclid})
    _complete(client, sfwid)

    assert _pixel(client, fbclid)["platform"] == "meta"


def test_ambiguous_ad_rid_fires_nothing(env):
    client, url_params, _ = env
    for _ in range(2):
        _complete(client, _add_record(url_params, traffic_source="meta", respondentId="DUP-123456"))

    assert _pixel(client, "DUP-123456") is None


def test_ad_rid_not_from_ad_traffic_fires_nothing(env):
    client, url_params, _ = env
    _complete(client, _add_record(url_params, traffic_source="direct", respondentId="VENDOR-998877"))

    assert _pixel(client, "VENDOR-998877") is None


# --- landing page base pixel (PageView) -------------------------------------

@pytest.mark.parametrize("query", [
    {"fbclid": "IwZXh0bgNhZW0CMTEA"},                      # what Meta ads actually send today
    {"utm_source": "meta", "utm_medium": "paid_social"},
])
def test_landing_pixel_for_meta_ad_click(env, query):
    client, _, database = env
    resp = client.get("/api/adpixel/landing", params={"api": "false", "vid": "5725", **query})

    assert resp.json() == {"pixel": {"platform": "meta", "pixel_id": PIXEL_ID}}
    assert resp.headers["cache-control"] == "no-store"
    assert database["ad_pixel_fires"].docs == []  # landing never counts as a fire


@pytest.mark.parametrize("query", [
    {"api": "false", "vid": "5068", "rid": "12345"},  # vendor traffic: never tracked
    {"utm_source": "newsletter"},
    {"ttclid": "abc"},                                 # TikTok present but disabled
])
def test_landing_pixel_null_for_non_ad_or_disabled(env, query):
    client, _, _ = env
    assert client.get("/api/adpixel/landing", params=query).json() == {"pixel": None}


# --- entry-side capture -----------------------------------------------------

def test_entry_capture_meta():
    params = {"utm_source": "facebook", "utm_medium": "paid", "campaign_id": "1", "adset_id": "2",
              "ad_id": "3", "placement": "Instagram_Feed", "fbclid": "abc", "vid": "9"}
    fields = extract_ad_tracking(params, {"fbp": "fb.1.1.111"}, {})

    assert fields["traffic_source"] == "meta"
    t = fields["adTracking"]
    assert (t["utm_source"], t["campaign_id"], t["adset_id"], t["ad_id"], t["placement"]) == \
        ("facebook", "1", "2", "3", "Instagram_Feed")
    assert t["fbclid"] == "abc" and t["fbp"] == "fb.1.1.111"
    assert t["fbc"].startswith("fb.1.") and t["fbc"].endswith(".abc")  # derived from fbclid


def test_entry_capture_names_and_skips_unfilled_macros():
    params = {"utm_source": "meta", "campaign_id": "120201", "campaign_name": "IN Amazon Pay 18-45",
              "adset_name": "Mumbai Delhi", "ad_name": "Video v2", "site_source_name": "ig",
              "adset_id": "{{adset.id}}", "ad_id": "{{ad.id}}"}
    t = extract_ad_tracking(params, {}, {})["adTracking"]
    assert (t["campaign_id"], t["campaign_name"], t["adset_name"], t["ad_name"], t["site_source_name"]) == \
        ("120201", "IN Amazon Pay 18-45", "Mumbai Delhi", "Video v2", "ig")
    assert "adset_id" not in t and "ad_id" not in t  # preview links leave macros unfilled


def test_entry_capture_prefers_cookie_fbc_and_ignores_non_ad():
    fields = extract_ad_tracking({"fbclid": "abc"}, {}, {"_fbc": "fb.1.5.abc", "_fbp": "fb.1.5.9"})
    assert fields["adTracking"]["fbc"] == "fb.1.5.abc"
    assert extract_ad_tracking({"vid": "1", "rid": "x"}, {}, {}) == {"traffic_source": "direct"}
    assert derive_traffic_source({"gclid": "g"}) == "google_ads"
    assert derive_traffic_source({"utm_source": "newsletter"}) == "newsletter"
