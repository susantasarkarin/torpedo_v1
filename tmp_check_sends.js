print("Total sends: " + db.outreach_sends_v2.countDocuments({}));
print("\nLatest 5 sends:");
db.outreach_sends_v2.find({}).sort({sent_at: -1}).limit(5).forEach(d => {
  printjson({email: d.email, sent_at: d.sent_at, from: d.from_email, step: d.step_number, campaign_id: d.campaign_id});
});
