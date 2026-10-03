from collections import Counter

import leads.inhouse_verifier as iv


def test_pattern_detection():
    assert iv.pattern_of("jane.roe@acme.com", "Jane Roe") == "first.last"
    assert iv.pattern_of("jroe@acme.com", "Jane Roe") == "flast"
    assert iv.pattern_of("jane@acme.com", "Jane") == "first"
    assert iv.pattern_of("sales@acme.com", "Jane Roe") is None


class _Ev:
    bounced = {"gone@acme.com"}
    delivered = {"jane.roe@acme.com"}
    wrote_to_us = {"buyer@client.com"}
    bounce_rate = {"flaky.com": 0.45, "acme.com": 0.05}
    patterns = {"acme.com": Counter({"first.last": 3})}


def _v(email, name="", monkeypatch=None):
    return iv.verify(email, name, _Ev())


def test_verdicts(monkeypatch):
    import scripts.verification_gate as vg
    monkeypatch.setattr(vg, "_has_mx_or_a", lambda d: True)
    assert _v("buyer@client.com")["verdict"] == "valid"
    assert _v("jane.roe@acme.com")["verdict"] == "valid"
    assert _v("gone@acme.com")["verdict"] == "invalid"
    assert _v("info@acme.com")["verdict"] == "invalid"            # role address
    assert _v("x.y@flaky.com", "X Y")["verdict"] == "risky"
    assert _v("tom.lee@acme.com", "Tom Lee")["verdict"] == "likely"
    assert _v("tlee@acme.com", "Tom Lee")["verdict"] == "unknown"  # acme uses first.last
    assert _v("tom@nowhere.io", "Tom")["verdict"] == "unknown"


def test_sendable_follows_verdict(monkeypatch):
    """Owner policy 2026-10-03: valid + likely sendable, invalid + risky not,
    unknown left untouched."""
    import scripts.verification_gate as vg
    monkeypatch.setattr(vg, "_has_mx_or_a", lambda d: True)
    monkeypatch.setattr(iv, "Evidence", lambda client: _Ev())

    class _Col:
        def __init__(self, docs):
            self.docs = docs

        def find(self, q, proj=None):
            return [d for d in self.docs if d["workflow_status"] in q["workflow_status"]["$in"]]

        def update_one(self, f, u):
            next(d for d in self.docs if d["_id"] == f["_id"]).update(u["$set"])

    rows = {"buyer@client.com": "", "tom.lee@acme.com": "Tom Lee", "gone@acme.com": "",
            "x.y@flaky.com": "X Y", "tom@nowhere.io": "Tom"}
    col = _Col([{"_id": i, "email": e, "name": n, "workflow_status": "not_started", "sendable": "untouched"}
                for i, (e, n) in enumerate(rows.items())])
    iv.score_outreach_leads({"torpedo": {"outreach_leads_v2": col}}, apply=True)
    got = {d["email"]: d["sendable"] for d in col.docs}
    assert got == {"buyer@client.com": True, "tom.lee@acme.com": True, "gone@acme.com": False,
                   "x.y@flaky.com": False, "tom@nowhere.io": "untouched"}
