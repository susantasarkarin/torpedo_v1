// Set next_send_at to now for all SFW not_started leads so they become due
var now = new Date();
var result = db.outreach_leads_v2.updateMany(
  {
    campaign_id: "2a451219-3ce3-43fe-91d3-e1a3155f5363",
    workflow_status: "not_started"
  },
  {
    $set: {
      next_send_at: now,
      updated_at: now
    }
  }
);
print("Updated SFW leads: " + result.modifiedCount);

// Also do the same for Cogentix
var result2 = db.outreach_leads_v2.updateMany(
  {
    campaign_id: "a981bdcd-fbd5-497a-8522-e886e9c2f57c",
    workflow_status: "not_started"
  },
  {
    $set: {
      next_send_at: now,
      updated_at: now
    }
  }
);
print("Updated Cogentix leads: " + result2.modifiedCount);

// Verify
var dueSFW = db.outreach_leads_v2.countDocuments({
  campaign_id: "2a451219-3ce3-43fe-91d3-e1a3155f5363",
  workflow_status: "not_started",
  next_send_at: {$lte: now}
});
print("SFW due now: " + dueSFW);
