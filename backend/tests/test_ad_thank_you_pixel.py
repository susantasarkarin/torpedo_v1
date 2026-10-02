"""
/surveycomplete -> /adpixel thank-you page + ad pixel (services/ad_tracking.py).

Pixel renders only for: well-formed RID -> existing COMPLETE record -> ad
traffic_source with an enabled platform -> not already fired. Every failure shows the same
thank-you page with no pixel code. Vendor (non-ad) traffic keeps its redirect.
"""
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.traffic as traffic
from services.ad_tracking import derive_traffic_source, extract_ad_tracking

THANK_YOU = "Thank you! Your response has been recorded."
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


def _complete_and_land(client, rid):
    """Client survey -> /surveycomplete -> 302 -> /adpixel."""
    resp = _complete(client, rid)
    assert resp.status_code == 302
    assert resp.headers["location"] == f"/adpixel?rid={rid}"
    return client.get("/adpixel", params={"rid": rid})


def test_valid_first_completion_renders_meta_pixel(env):
    client, url_params, database = env
    rid = _add_record(url_params, traffic_source="meta")

    resp = _complete_and_land(client, rid)

    assert resp.status_code == 200
    assert THANK_YOU in resp.text
    assert f"fbq('init', \"{PIXEL_ID}\")" in resp.text
    assert "fbq('track', 'PageView')" in resp.text
    assert (
        f"fbq('trackCustom', 'SurveyComplete', {{survey_id: \"SV-42\"}}, {{eventID: \"complete_{rid}\"}})"
        in resp.text
    )
    assert resp.headers["cache-control"] == "no-store"
    record = url_params.docs[0]
    assert record["status"] == "COMPLETE"  # existing completion logic still ran
    assert record["ad_pixel_fired_at"] is not None
    fires = database["ad_pixel_fires"].docs
    assert len(fires) == 1 and fires[0]["rid"] == rid and fires[0]["platform"] == "meta"


def test_refresh_does_not_fire_twice(env):
    client, url_params, database = env
    rid = _add_record(url_params, traffic_source="meta")

    _complete_and_land(client, rid)
    resp = client.get("/adpixel", params={"rid": rid})  # refresh
    assert "fbq(" not in resp.text
    resp = _complete_and_land(client, rid)  # reused completion link

    assert resp.status_code == 200
    assert THANK_YOU in resp.text
    assert "fbq(" not in resp.text
    assert len(database["ad_pixel_fires"].docs) == 1


@pytest.mark.parametrize("path", ["/surveycomplete", "/adpixel"])
def test_unknown_rid_shows_page_without_pixel(env, path):
    client, _, database = env

    resp = client.get(path, params={"rid": str(ObjectId())}, follow_redirects=False)

    assert resp.status_code == 200
    assert THANK_YOU in resp.text
    assert "fbq(" not in resp.text
    assert database["ad_pixel_fires"].docs == []


def test_adpixel_before_completion_fires_nothing(env):
    """/adpixel is public: hitting it with a mid-survey RID must not fire."""
    client, url_params, database = env
    rid = _add_record(url_params, traffic_source="meta")  # INCOMPLETE

    resp = client.get("/adpixel", params={"rid": rid})

    assert resp.status_code == 200 and THANK_YOU in resp.text
    assert "fbq(" not in resp.text
    assert "ad_pixel_fired_at" not in url_params.docs[0]
    # ...and the real completion afterwards still fires once
    assert "fbq('trackCustom'" in _complete_and_land(client, rid).text


def test_non_ad_traffic_keeps_vendor_flow_and_no_pixel(env):
    client, url_params, _ = env
    rid = _add_record(url_params, traffic_source="direct")

    resp = _complete(client, rid)

    assert resp.status_code in (302, 307)  # unchanged redirect behaviour
    assert "fbq(" not in resp.text
    assert "ad_pixel_fired_at" not in url_params.docs[0]


def test_ad_traffic_with_disabled_platform_renders_no_pixel(env):
    client, url_params, _ = env
    rid = _add_record(url_params, traffic_source="tiktok")  # present in config, disabled

    resp = _complete_and_land(client, rid)

    assert resp.status_code == 200 and THANK_YOU in resp.text
    assert "<script" not in resp.text
    assert "ad_pixel_fired_at" not in url_params.docs[0]


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

    for path in ("/surveycomplete", "/adpixel"):
        resp = client.get(path, params={"rid": bad_rid}, follow_redirects=False)
        assert resp.status_code == 200
        assert THANK_YOU in resp.text
        assert "fbq(" not in resp.text
        assert "<script>alert" not in resp.text and "Purchase" not in resp.text
    assert database["ad_pixel_fires"].docs == []


def test_survey_id_is_escaped_in_script(env):
    client, url_params, _ = env
    rid = _add_record(url_params, traffic_source="meta", assignedSurveyId='x"</script><script>alert(1)//')

    resp = _complete_and_land(client, rid)

    assert "</script><script>alert" not in resp.text
    assert "\\u003c/script\\u003e" in resp.text


def test_terminate_unchanged_for_ad_traffic(env):
    client, url_params, _ = env
    rid = _add_record(url_params, traffic_source="meta")

    resp = client.get("/surveyterminate", params={"rid": rid}, follow_redirects=False)

    assert resp.status_code in (302, 307)
    assert "ad_pixel_fired_at" not in url_params.docs[0]


# --- /adpixel reached with the ad-side identifier ----------------------------

def test_adpixel_by_ad_rid_fires_once_with_that_event_id(env):
    """rid on /adpixel = the id that came in on the ad URL (respondentId)."""
    client, url_params, database = env
    sfwid = _add_record(url_params, traffic_source="meta", respondentId="FB-7781234")
    _complete(client, sfwid)  # client survey reports completion with our SFWID

    resp = client.get("/adpixel", params={"rid": "FB-7781234"})

    assert "{eventID: \"complete_FB-7781234\"}" in resp.text
    assert "fbq(" not in client.get("/adpixel", params={"rid": "FB-7781234"}).text
    assert "fbq(" not in client.get("/adpixel", params={"rid": sfwid}).text  # same person, other id
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
    page = client.get("/adpixel", params={"rid": "ad-1b2c3d4e"})
    assert "{eventID: \"complete_ad-1b2c3d4e\"}" in page.text


def test_adpixel_by_fbclid(env):
    client, url_params, _ = env
    fbclid = "IwAR2xYz_abc-123"
    sfwid = _add_record(url_params, traffic_source="meta", adTracking={"fbclid": fbclid})
    _complete(client, sfwid)

    assert "fbq('trackCustom'" in client.get("/adpixel", params={"rid": fbclid}).text


def test_adpixel_ambiguous_ad_rid_fires_nothing(env):
    client, url_params, _ = env
    for _ in range(2):
        _complete(client, _add_record(url_params, traffic_source="meta", respondentId="DUP-123456"))

    assert "fbq(" not in client.get("/adpixel", params={"rid": "DUP-123456"}).text


def test_adpixel_ad_rid_not_from_ad_traffic_fires_nothing(env):
    client, url_params, _ = env
    _complete(client, _add_record(url_params, traffic_source="direct", respondentId="VENDOR-998877"))

    assert "fbq(" not in client.get("/adpixel", params={"rid": "VENDOR-998877"}).text


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


def test_entry_capture_prefers_cookie_fbc_and_ignores_non_ad():
    fields = extract_ad_tracking({"fbclid": "abc"}, {}, {"_fbc": "fb.1.5.abc", "_fbp": "fb.1.5.9"})
    assert fields["adTracking"]["fbc"] == "fb.1.5.abc"
    assert extract_ad_tracking({"vid": "1", "rid": "x"}, {}, {}) == {"traffic_source": "direct"}
    assert derive_traffic_source({"gclid": "g"}) == "google_ads"
    assert derive_traffic_source({"utm_source": "newsletter"}) == "newsletter"
