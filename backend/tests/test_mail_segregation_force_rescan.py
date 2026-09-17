"""
Covers the force_rescan chunking fix (2026-09-17): a single collection-wide
update_many({}, {"$unset": ...}) timed out against the real 367,698-email
pool (MongoDB's default 20s socket timeout). Fixed by chunking the clear by
_id, matching the batching already used elsewhere in this function.

Mocks the module-level `mail_pool_emails` collection directly -- no live
Mongo needed to verify the chunking behavior itself.
"""
from unittest.mock import MagicMock, patch

from agents import mail_segregation_agent as msa


def _fake_ids(n):
    return [{"_id": i} for i in range(n)]


def _empty_cursor():
    """The main classification loop does find(...).limit(n) -- a plain
    list doesn't support .limit(), so an empty "no more work" result needs
    a cursor-like mock, not a bare list."""
    cursor = MagicMock()
    cursor.limit.return_value = []
    return cursor


def test_force_rescan_clears_in_chunks_not_one_call():
    fake_coll = MagicMock()
    fake_coll.count_documents.return_value = 5000
    # First find() call is the clear step's find({}, {"_id": 1}) -- iterated
    # directly, no .limit(). Second is the main loop's find(...).limit(n) --
    # terminate it immediately since this test only covers the clearing step.
    fake_coll.find.side_effect = [_fake_ids(5000), _empty_cursor()]

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
    fake_coll.find.side_effect = [[], _empty_cursor()]
    fake_coll.count_documents.return_value = 0

    with patch.object(msa, "mail_pool_emails", fake_coll):
        agent = msa.MailSegregationAgent()
        with patch.object(agent, "_generate_segment_summaries", return_value=[]):
            result = agent.segregate_all_emails(force_rescan=True)

    fake_coll.update_many.assert_not_called()
    assert result["success"] is True
