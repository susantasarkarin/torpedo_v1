// Count leads by campaign and status
var campaigns = db.outreach_leads_v2.aggregate([
  {$group: {_id: {campaign_id: "$campaign_id", workflow_status: "$workflow_status"}, count: {$sum: 1}}},
  {$sort: {"_id.campaign_id": 1, "_id.workflow_status": 1}}
]).toArray();
campaigns.forEach(c => print(c._id.campaign_id + " | " + c._id.workflow_status + " | " + c.count));
