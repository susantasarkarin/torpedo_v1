// Bulk mark all not_started leads in campaign 00ff5440 as error (no templates)
var result = db.outreach_leads_v2.updateMany(
  {
    campaign_id: "00ff5440-2df2-46fc-843b-f3db3cd81e94",
    workflow_status: "not_started"
  },
  {
    $set: {
      workflow_status: "error",
      last_send_error: "Campaign has no template content - bulk marked",
      last_send_error_at: new Date(),
      updated_at: new Date()
    }
  }
);
print("Matched: " + result.matchedCount + ", Modified: " + result.modifiedCount);

// Verify
var remaining = db.outreach_leads_v2.countDocuments({
  campaign_id: "00ff5440-2df2-46fc-843b-f3db3cd81e94",
  workflow_status: "not_started"
});
print("Remaining not_started: " + remaining);
