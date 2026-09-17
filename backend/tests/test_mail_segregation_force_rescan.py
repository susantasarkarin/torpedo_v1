"""
Covers two force_rescan reliability fixes made 2026-09-17, both found live
against the real 367,698-email pool:

1. A single collection-wide update_many({}, {"$unset": ...}) for the initial
   field-clear exceeded MongoDB's default 20s socket timeout. Fixed by
   chunking the clear by _id (2000/chunk).

2. The main classification loop re-queried find({}).limit(n) every
   iteration with no cursor tracking. This relies on WiredTiger's document
   relocation-on-update behavior to incidentally make progress through the
   collection (updating a doc grows it, which can relocate it on disk) --
   fragile, and it degraded into the same timeout deeper into a real run
   (confirmed live: 1,500 docs processed, then timeout). Fixed with
   explicit sort("_id", 1) + a $gt cursor tracking the last-seen _id, which
   guarantees complete, non-overlapping, deterministic coverage regardless
   of in-place mutation.

3. A real 367,698-email run got 9x further with fix #2 in place (14,000
   emails processed, vs. 1,500 before) but then hit the SAME timeout --
   not a query problem this time (the read side is now an efficient
   indexed range scan), almost certainly connection/resource contention
   from running continuously for several minutes on a shared, constrained
   box. Fixed with a bounded retry-with-backoff (_retry_db_op) around the
   actual I/O calls (find/bulk_write), not the pure-Python classify step.

Mocks the module-level `mail_pool_emails` collection directly -- no live
Mongo needed to verify any of the three fixes. Patches time.sleep so retry
backoff tests run instantly.
"""
from unittest.mock import MagicMock, patch

from pymongo.errors import AutoReconnect

from agents import mail_segregation_agent as msa


def _fake_ids(n):
    return [{"_id": i} for i in range(n)]


def _cursor(docs):
    """find(...).sort(...).limit(...) all need to be chainable and return
    something list()-able at the end."""
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = docs
    return cursor


def test_force_rescan_clears_in_chunks_not_one_call():
    fake_coll = MagicMock()
    fake_coll.count_documents.return_value = 5000
    # First find() call is the clear step's find({}, {"_id": 1}) -- iterated
    # directly, no .sort()/.limit(). Second is the main loop's
    # find(...).sort(...).limit(n) -- terminate it immediately, this test
    # only covers the clearing step.
    fake_coll.find.side_effect = [_fake_ids(5000), _cursor([])]

    with patch.object(msa, "mail_pool_emails", fake_coll):
        agent = msa.MailSegregationAgent()
        with patch.object(agent, "_generate_segment_summaries", return_value=[]):
            agent.segregate_all_emails(force_rescan=True, batch_size=100)

    # 5000 ids / 2000-per-chunk = 3 update_many calls, not 1.
    assert fake_coll.update_many.call_count == 3
    for call in fake_coll.update_many.call_args_list:
        filter_arg = call.args[0]
        assert "_id" in filter_arg and "$in" in filter_arg["_id"]
        assert len(filter_arg["_id"]["$in"]) <= 2000
    # No call filters on the whole collection ({}) for the clear step.
    assert all(c.args[0] != {} for c in fake_coll.update_many.call_args_list)


def test_force_rescan_with_no_documents_clears_nothing():
    fake_coll = MagicMock()
    fake_coll.find.side_effect = [[], _cursor([])]
    fake_coll.count_documents.return_value = 0

    with patch.object(msa, "mail_pool_emails", fake_coll):
        agent = msa.MailSegregationAgent()
        with patch.object(agent, "_generate_segment_summaries", return_value=[]):
            result = agent.segregate_all_emails(force_rescan=True)

    fake_coll.update_many.assert_not_called()
    assert result["success"] is True


def test_force_rescan_pages_by_id_cursor_not_repeated_empty_filter():
    """Three pages of real-shaped docs, then empty -- the loop must query
    with an increasing _id cursor each time, not the same {} every call."""
    fake_coll = MagicMock()
    fake_coll.count_documents.return_value = 3

    page1 = [{"_id": 1, "from_email": "a@x.com", "subject": ""}]
    page2 = [{"_id": 2, "from_email": "b@x.com", "subject": ""}]
    page3 = [{"_id": 3, "from_email": "c@x.com", "subject": ""}]

    fake_coll.find.side_effect = [
        [],  # clear step: no docs to clear
        _cursor(page1),
        _cursor(page2),
        _cursor(page3),
        _cursor([]),  # terminates the loop
    ]

    with patch.object(msa, "mail_pool_emails", fake_coll):
        agent = msa.MailSegregationAgent()
        with patch.object(agent, "_generate_segment_summaries", return_value=[]):
            result = agent.segregate_all_emails(force_rescan=True, batch_size=1)

    assert result["success"] is True
    assert result["processed"] == 3

    # Calls: [0]=clear-step find, [1..4]=main loop pages.
    main_loop_calls = fake_coll.find.call_args_list[1:]
    assert main_loop_calls[0].args[0] == {}  # first page: no cursor yet
    assert main_loop_calls[1].args[0] == {"_id": {"$gt": 1}}
    assert main_loop_calls[2].args[0] == {"_id": {"$gt": 2}}
    assert main_loop_calls[3].args[0] == {"_id": {"$gt": 3}}


def test_non_force_rescan_still_uses_the_unclassified_filter_not_id_paging():
    """The normal (non-rescan) path must be untouched: it should keep using
    _classified_filter(exists=False), not the new _id-cursor logic."""
    fake_coll = MagicMock()
    fake_coll.count_documents.return_value = 0
    fake_coll.find.return_value = _cursor([])

    with patch.object(msa, "mail_pool_emails", fake_coll):
        agent = msa.MailSegregationAgent()
        with patch.object(agent, "_generate_segment_summaries", return_value=[]):
            agent.segregate_all_emails(force_rescan=False)

    fake_coll.update_many.assert_not_called()  # no clearing on a normal run
    call_filter = fake_coll.find.call_args_list[0].args[0]
    assert "_id" not in call_filter


# ============================================================
# _retry_db_op() -- the resilience fix for the real timeout that recurred
# at 14,000 processed emails despite the pagination fix
# ============================================================

def test_retry_db_op_succeeds_after_transient_failures():
    agent = msa.MailSegregationAgent()
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise AutoReconnect("connection reset")
        return "ok"

    with patch("agents.mail_segregation_agent.time.sleep") as mock_sleep:
        result = agent._retry_db_op(flaky)

    assert result == "ok"
    assert calls["n"] == 3
    assert mock_sleep.call_count == 2  # backoff between attempts 1->2 and 2->3


def test_retry_db_op_raises_after_max_attempts():
    agent = msa.MailSegregationAgent()

    def always_fails():
        raise AutoReconnect("still down")

    with patch("agents.mail_segregation_agent.time.sleep"):
        try:
            agent._retry_db_op(always_fails)
            assert False, "expected AutoReconnect to propagate"
        except AutoReconnect:
            pass


def test_segregate_all_emails_survives_one_transient_batch_failure():
    """The scenario that actually happened in production: a batch's
    bulk_write times out once, then succeeds on retry -- the whole run must
    not die, and progress (last_id) must not skip the retried batch."""
    fake_coll = MagicMock()
    fake_coll.count_documents.return_value = 1
    page = [{"_id": 1, "from_email": "a@x.com", "subject": ""}]
    fake_coll.find.side_effect = [[], _cursor(page), _cursor([])]

    call_count = {"n": 0}

    def flaky_bulk_write(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise AutoReconnect("connection reset")
        return MagicMock()

    fake_coll.bulk_write.side_effect = flaky_bulk_write

    with patch.object(msa, "mail_pool_emails", fake_coll), \
         patch.object(msa, "classified_emails", MagicMock()), \
         patch("agents.mail_segregation_agent.time.sleep"):
        agent = msa.MailSegregationAgent()
        with patch.object(agent, "_generate_segment_summaries", return_value=[]):
            result = agent.segregate_all_emails(force_rescan=True, batch_size=1)

    assert result["success"] is True
    assert result["processed"] == 1
    assert call_count["n"] == 2  # one failure, one successful retry
