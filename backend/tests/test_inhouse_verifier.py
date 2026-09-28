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
