// Part 1 - Send status
print("=== SEND STATUS ===");
print("Total sends: " + db.outreach_sends_v2.countDocuments({}));
db.outreach_sends_v2.aggregate([
  {$group: {_id: "$campaign_id", count: {$sum: 1}}}
]).forEach(r => print("  campaign " + r._id + ": " + r.count));

print("\nLead status:");
db.outreach_leads_v2.aggregate([
  {$group: {_id: {cid: "$campaign_id", ws: "$workflow_status"}, count: {$sum: 1}}},
  {$sort: {"_id.cid": 1, "_id.ws": 1}}
]).forEach(r => print("  " + r._id.cid.substring(0,8) + " | " + r._id.ws + " | " + r.count));

print("\nLatest 3 sends:");
db.outreach_sends_v2.find({},{email:1,sent_at:1,from_email:1,status:1}).sort({sent_at:-1}).limit(3).forEach(d => {
  print("  " + d.sent_at.toISOString() + " | " + d.email + " | " + d.from_email + " | " + (d.status||"n/a"));
});
