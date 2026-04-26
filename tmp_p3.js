// Part 3 - Activity tracking (opens, replies, clicks)
print("=== ACTIVITY ===");

// Check send record fields for activity
print("Sends with opened=true: " + db.outreach_sends_v2.countDocuments({opened:true}));
print("Sends with open_count>0: " + db.outreach_sends_v2.countDocuments({open_count:{$gt:0}}));
print("Sends with replied=true: " + db.outreach_sends_v2.countDocuments({replied:true}));
print("Sends with clicked=true: " + db.outreach_sends_v2.countDocuments({clicked:true}));

// Check lead-level
print("Leads replied: " + db.outreach_leads_v2.countDocuments({workflow_status:"replied"}));
print("Leads opened: " + db.outreach_leads_v2.countDocuments({workflow_status:"opened"}));
print("Leads completed: " + db.outreach_leads_v2.countDocuments({workflow_status:"completed"}));

// Check gmail metadata for inbound
var gdb = db.getSiblingDB("torpedo_gmail");
var oneDayAgo = new Date(Date.now() - 24*60*60*1000);
print("\nGmail inbound (24h): " + gdb.email_metadata.countDocuments({direction:"inbound", received_at:{$gte:oneDayAgo}}));
print("Gmail inbound (24h, classified): " + gdb.email_metadata.countDocuments({direction:"inbound", classification:{$exists:true}, received_at:{$gte:oneDayAgo}}));

// Distinct classifications
print("Distinct classifications: " + JSON.stringify(gdb.email_metadata.distinct("classification")));

// Sample send record schema
print("\n=== SAMPLE SEND RECORD ===");
var s = db.outreach_sends_v2.findOne({});
if (s) printjson(s);
