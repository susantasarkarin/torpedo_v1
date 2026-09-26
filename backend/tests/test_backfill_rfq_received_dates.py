"""
Unit tests for scripts/backfill_rfq_received_dates.py -- mocked Mongo, no
real DB. Covers: only sets received_at (never touches any other field),
skips a record whose source email is missing or dateless, and dry-run
performs no writes.
"""
import importlib.util
from bson import ObjectId
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "scripts", "backfill_rfq_received_dates.py")
_spec = importlib.util.spec_from_file_location("backfill_rfq_received_dates", _PATH)
backfill = importlib.util.module_from_spec(_spec)
sys.modules["backfill_rfq_received_dates"] = backfill
_spec.loader.exec_module(backfill)


def _run(argv, opps_docs, email_by_id):
    fake_opps = MagicMock()
    fake_opps.find.return_value = opps_docs
    fake_mail = MagicMock()
    fake_mail.find_one.side_effect = lambda q, proj=None: email_by_id.get(str(q["_id"]))

    fake_db_manager = MagicMock()
    fake_db_manager.client = {"crm_db": {"opportunities": fake_opps}}
    fake_get_db = MagicMock(return_value={"email_metadata": fake_mail})

    with patch("database.get_db_manager", return_value=fake_db_manager), \
         patch("db_pools.get_db", fake_get_db), \
         patch("sys.argv", ["prog"] + argv):
        backfill.main()
    return fake_opps


def test_dry_run_makes_no_update_calls(tmp_path):
    docs = [{"_id": "o1", "metadata": {"rfq": {"source_email_id": "5f50c31e8b1e2c001f8e4a11"}}}]
    email_by_id = {"5f50c31e8b1e2c001f8e4a11": {"date": datetime(2021, 12, 17)}}
    fake_opps = _run(["--dry-run"], docs, email_by_id)
    fake_opps.update_one.assert_not_called()


def test_real_run_sets_only_received_at():
    docs = [{"_id": "o1", "metadata": {"rfq": {"source_email_id": "5f50c31e8b1e2c001f8e4a11"}}}]
    email_by_id = {"5f50c31e8b1e2c001f8e4a11": {"date": datetime(2021, 12, 17)}}
    fake_opps = _run([], docs, email_by_id)
    fake_opps.update_one.assert_called_once()
    query, update = fake_opps.update_one.call_args.args
    assert query == {"_id": "o1"}
    assert update == {"$set": {"metadata.rfq.received_at": datetime(2021, 12, 17)}}


def test_skips_when_source_email_missing():
    docs = [{"_id": "o1", "metadata": {"rfq": {"source_email_id": "5f50c31e8b1e2c001f8e4a99"}}}]
    fake_opps = _run([], docs, {})
    fake_opps.update_one.assert_not_called()


def test_skips_when_source_email_has_no_date():
    docs = [{"_id": "o1", "metadata": {"rfq": {"source_email_id": "5f50c31e8b1e2c001f8e4a11"}}}]
    email_by_id = {"5f50c31e8b1e2c001f8e4a11": {}}
    fake_opps = _run([], docs, email_by_id)
    fake_opps.update_one.assert_not_called()


def test_uses_timestamp_when_date_is_absent():
    docs = [{"_id": "o1", "metadata": {"rfq": {"source_email_id": "5f50c31e8b1e2c001f8e4a11"}}}]
    email_by_id = {"5f50c31e8b1e2c001f8e4a11": {"timestamp": datetime(2020, 6, 23)}}
    fake_opps = _run([], docs, email_by_id)
    _, update = fake_opps.update_one.call_args.args
    assert update["$set"]["metadata.rfq.received_at"] == datetime(2020, 6, 23)
