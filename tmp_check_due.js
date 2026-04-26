// Check next_send_at for SFW leads
var now = new Date();
print("Current time: " + now.toISOString());

var due = db.outreach_leads_v2.countDocuments({
  campaign_id: "2a451219-3ce3-43fe-91d3-e1a3155f5363",
  workflow_status: {$in: ["not_started", "pending_scheduled", "in_sequence"]},
  next_send_at: {$lte: now}
});
print("SFW due now: " + due);

var notDue = db.outreach_leads_v2.countDocuments({
  campaign_id: "2a451219-3ce3-43fe-91d3-e1a3155f5363",
  workflow_status: {$in: ["not_started", "pending_scheduled", "in_sequence"]},
  next_send_at: {$gt: now}
});
print("SFW not due yet: " + notDue);

var noNext = db.outreach_leads_v2.countDocuments({
  campaign_id: "2a451219-3ce3-43fe-91d3-e1a3155f5363",
  workflow_status: {$in: ["not_started", "pending_scheduled", "in_sequence"]},
  next_send_at: {$exists: false}
});
print("SFW no next_send_at: " + noNext);

// Show a sample lead
var sample = db.outreach_leads_v2.findOne({campaign_id: "2a451219-3ce3-43fe-91d3-e1a3155f5363"});
printjson({
  email: sample.email,
  workflow_status: sample.workflow_status,
  next_send_at: sample.next_send_at,
  current_step: sample.current_step,
  enrolled_at: sample.enrolled_at
});

// Also check Cogentix
var dueCog = db.outreach_leads_v2.countDocuments({
  campaign_id: "a981bdcd-fbd5-497a-8522-e886e9c2f57c",
  workflow_status: {$in: ["not_started", "pending_scheduled", "in_sequence"]},
  next_send_at: {$lte: now}
});
print("Cogentix due now: " + dueCog);
