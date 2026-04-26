// Full status breakdown
var campaigns = db.outreach_leads_v2.aggregate([
  {$group: {_id: {cid: "$campaign_id", ws: "$workflow_status"}, count: {$sum: 1}}},
  {$sort: {"_id.cid": 1, "_id.ws": 1}}
]).toArray();
campaigns.forEach(c => print(c._id.cid + " | " + c._id.ws + " | " + c.count));

print("\n--- Total leads per campaign ---");
var totals = db.outreach_leads_v2.aggregate([
  {$group: {_id: "$campaign_id", count: {$sum: 1}}}
]).toArray();
totals.forEach(t => print(t._id + " | " + t.count));

print("\n--- Send records ---");
print("Total sends: " + db.outreach_sends_v2.countDocuments({}));
var sends = db.outreach_sends_v2.aggregate([
  {$group: {_id: "$campaign_id", count: {$sum: 1}}}
]).toArray();
sends.forEach(s => print(s._id + " | " + s.count));

print("\n--- Latest 5 sends ---");
db.outreach_sends_v2.find({}, {email: 1, sent_at: 1, campaign_id: 1}).sort({sent_at: -1}).limit(5).forEach(d => printjson(d));
