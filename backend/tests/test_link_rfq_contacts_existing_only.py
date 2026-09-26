"""
Unit tests for scripts/link_rfq_contacts_existing_only.py -- mocked Mongo.
Covers: links only to an ALREADY-EXISTING contact (never creates one), also
carries over the contact's account_id when the opportunity has none, skips
when no contact matches or the sender is unrecoverable, and dry-run performs
no writes.
"""
import importlib.util
from bson import ObjectId
import os
import sys
from unittest.mock import MagicMock, patch

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "scripts", "link_rfq_contacts_existing_only.py")
_spec = importlib.util.spec_from_file_location("link_rfq_contacts_existing_only", _PATH)
link_script = importlib.util.module_from_spec(_spec)
sys.modules["link_rfq_contacts_existing_only"] = link_script
_spec.loader.exec_module(link_script)


def _run(argv, opps_docs, email_by_id, contact_by_email):
    fake_opps = MagicMock()
    fake_opps.find.return_value = opps_docs
    fake_mail = MagicMock()
    fake_mail.find_one.side_effect = lambda q, proj=None: email_by_id.get(str(q["_id"]))

    fake_db_manager = MagicMock()
    fake_db_manager.client = {"crm_db": {"opportunities": fake_opps}}
    fake_get_db = MagicMock(return_value={"email_metadata": fake_mail})
    fake_find_contact = MagicMock(side_effect=lambda email: contact_by_email.get(email))

    with patch("database.get_db_manager", return_value=fake_db_manager), \
         patch("db_pools.get_db", fake_get_db), \
         patch("app.services.crm_service.find_contact_by_email", fake_find_contact), \
         patch("sys.argv", ["prog"] + argv):
        link_script.main()
    return fake_opps


def test_links_to_an_existing_contact_only():
    docs = [{"_id": "o1", "account_id": None, "metadata": {"rfq": {"source_email_id": "5f50c31e8b1e2c001f8e4a11"}}}]
    email_by_id = {"5f50c31e8b1e2c001f8e4a11": {"from_email": "buyer@client.com"}}
    contacts = {"buyer@client.com": {"_id": "c1", "account_id": None}}
    fake_opps = _run([], docs, email_by_id, contacts)
    fake_opps.update_one.assert_called_once()
    query, update = fake_opps.update_one.call_args.args
    assert query == {"_id": "o1"}
    assert update == {"$set": {"contact_id": "c1"}}


def test_carries_the_contacts_account_id_when_opportunity_has_none():
    docs = [{"_id": "o1", "account_id": None, "metadata": {"rfq": {"source_email_id": "5f50c31e8b1e2c001f8e4a11"}}}]
    email_by_id = {"5f50c31e8b1e2c001f8e4a11": {"from_email": "buyer@client.com"}}
    contacts = {"buyer@client.com": {"_id": "c1", "account_id": "acc1"}}
    fake_opps = _run([], docs, email_by_id, contacts)
    _, update = fake_opps.update_one.call_args.args
    assert update["$set"] == {"contact_id": "c1", "account_id": "acc1"}


def test_does_not_overwrite_an_existing_account_id():
    docs = [{"_id": "o1", "account_id": "already-set", "metadata": {"rfq": {"source_email_id": "5f50c31e8b1e2c001f8e4a11"}}}]
    email_by_id = {"5f50c31e8b1e2c001f8e4a11": {"from_email": "buyer@client.com"}}
    contacts = {"buyer@client.com": {"_id": "c1", "account_id": "acc1"}}
    fake_opps = _run([], docs, email_by_id, contacts)
    _, update = fake_opps.update_one.call_args.args
    assert "account_id" not in update["$set"]


def test_never_creates_a_contact_skips_when_no_match():
    docs = [{"_id": "o1", "account_id": None, "metadata": {"rfq": {"source_email_id": "5f50c31e8b1e2c001f8e4a11"}}}]
    email_by_id = {"5f50c31e8b1e2c001f8e4a11": {"from_email": "nobody-yet@client.com"}}
    fake_opps = _run([], docs, email_by_id, {})   # no contact matches
    fake_opps.update_one.assert_not_called()


def test_skips_when_source_email_or_sender_missing():
    docs = [{"_id": "o1", "account_id": None, "metadata": {"rfq": {"source_email_id": "5f50c31e8b1e2c001f8e4a99"}}},
            {"_id": "o2", "account_id": None, "metadata": {"rfq": {"source_email_id": "5f50c31e8b1e2c001f8e4a12"}}}]
    email_by_id = {"5f50c31e8b1e2c001f8e4a12": {"from_email": ""}}
    fake_opps = _run([], docs, email_by_id, {})
    fake_opps.update_one.assert_not_called()


def test_dry_run_makes_no_update_calls():
    docs = [{"_id": "o1", "account_id": None, "metadata": {"rfq": {"source_email_id": "5f50c31e8b1e2c001f8e4a11"}}}]
    email_by_id = {"5f50c31e8b1e2c001f8e4a11": {"from_email": "buyer@client.com"}}
    contacts = {"buyer@client.com": {"_id": "c1", "account_id": None}}
    fake_opps = _run(["--dry-run"], docs, email_by_id, contacts)
    fake_opps.update_one.assert_not_called()
