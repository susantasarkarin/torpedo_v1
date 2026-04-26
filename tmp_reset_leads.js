db = db.getSiblingDB('torpedo');

// Delete all send records (they went to the test email, not real recipients)
var delResult = db.outreach_sends_v2.deleteMany({});
print('Deleted send records: ' + delResult.deletedCount);

// Reset all in_sequence leads back to not_started
var resetResult = db.outreach_leads_v2.updateMany(
  { workflow_status: 'in_sequence' },
  { $set: { workflow_status: 'not_started', current_step: 0 }, $unset: { last_send_at: '', last_send_error: '' } }
);
print('Reset in_sequence leads: ' + resetResult.modifiedCount);

// Also reset the pending_scheduled ones
var resetPending = db.outreach_leads_v2.updateMany(
  { workflow_status: 'pending_scheduled' },
  { $set: { workflow_status: 'not_started', current_step: 0 }, $unset: { last_send_at: '', last_send_error: '' } }
);
print('Reset pending_scheduled leads: ' + resetPending.modifiedCount);

// Also clear last_send_error on any not_started leads that have it
var clearErrors = db.outreach_leads_v2.updateMany(
  { workflow_status: 'not_started', last_send_error: { $exists: true } },
  { $unset: { last_send_error: '' } }
);
print('Cleared errors on not_started leads: ' + clearErrors.modifiedCount);

// Final status check
print('=== FINAL STATUS ===');
printjson(db.outreach_leads_v2.aggregate([{$group:{_id:'$workflow_status', count:{$sum:1}}}]).toArray());
print('Total sends remaining: ' + db.outreach_sends_v2.countDocuments({}));
