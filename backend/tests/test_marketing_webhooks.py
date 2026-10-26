"""Meta / WhatsApp webhooks -> inbox (MARKETING_PLAN 3.5.2-3.5.3, 3.7)."""
import hashlib
import hmac
import json

from routers import marketing_webhooks as W

SET = {"page_ids": {"SFW": "111"}, "instagram_ids": {"COGENTIX": "222"}, "phone_number_ids": {"BIM": "333"}}


def test_signature():
    raw = b'{"a":1}'
    sig = "sha256=" + hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
    assert W.verify_signature(raw, sig, "s3cret")
    assert not W.verify_signature(raw, sig, "other") and not W.verify_signature(raw, None, "s3cret")
    assert not W.verify_signature(raw, sig, None)                      # no secret configured -> refuse


def test_parse_meta_comments_dms_leads_and_skips_own_and_echo():
    body = {"object": "page", "entry": [{"id": "111", "changes": [
        {"field": "feed", "value": {"item": "comment", "verb": "add", "comment_id": "c1", "post_id": "p1", "message": "Do you do CATI?",
                                    "from": {"id": "u9", "name": "Meera"}, "created_time": 1761450000}},
        {"field": "feed", "value": {"item": "comment", "verb": "add", "comment_id": "c2", "message": "our reply", "from": {"id": "111"}}},
        {"field": "leadgen", "value": {"leadgen_id": "L77", "form_id": "F1", "ad_id": "A1"}}],
        "messaging": [{"sender": {"id": "u9"}, "timestamp": 1761450000000, "message": {"mid": "m.1", "text": "hello"}},
                      {"sender": {"id": "111"}, "message": {"mid": "m.2", "text": "echo", "is_echo": True}}]}]}
    items, leads = W.parse_meta(body, SET)
    assert [(i["channel"], i["external_id"], i["bu"]) for i in items] == [("facebook_comment", "c1", "SFW"), ("messenger", "m.1", "SFW")]
    assert leads == [{"leadgen_id": "L77", "form_id": "F1", "page_id": "111", "bu": "SFW", "ad_id": "A1", "created_time": None}]
    ig = {"object": "instagram", "entry": [{"id": "222", "changes": [{"field": "comments", "value": {
        "id": "ic1", "text": "price?", "from": {"username": "ravi", "id": "u5"}, "media": {"id": "md1"}}}]}]}
    items, _ = W.parse_meta(ig, SET)
    assert items[0]["channel"] == "instagram_comment" and items[0]["bu"] == "COGENTIX"


def test_parse_whatsapp():
    body = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "333"}, "contacts": [{"wa_id": "919876543210", "profile": {"name": "Asha"}}],
        "messages": [{"id": "wamid.1", "from": "919876543210", "timestamp": "1761450000", "type": "text", "text": {"body": "STOP"}}],
        "statuses": [{"id": "x", "status": "read"}]}}]}]}
    items = W.parse_whatsapp(body, SET)
    assert items == [dict(channel="whatsapp", external_id="wamid.1", bu="BIM", text="STOP", at=W._ts("1761450000"),
                          author={"name": "Asha", "phone": "919876543210"}, kind="message", thread_id="919876543210")]
