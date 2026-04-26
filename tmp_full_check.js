// ========== 1. SEND STATUS ==========
print("=== SEND STATUS ===");
print("Total sends: " + db.outreach_sends_v2.countDocuments({}));

// By campaign
print("\nSends by campaign:");
db.outreach_sends_v2.aggregate([
  {$group: {_id: "$campaign_id", count: {$sum: 1}}},
  {$sort: {count: -1}}
]).forEach(r => {
  var camp = db.outreach_campaigns_v2.findOne({campaign_id: r._id}, {name: 1});
  print("  " + (camp ? camp.name : r._id) + ": " + r.count);
});

// Lead status breakdown
print("\nLead status breakdown:");
db.outreach_leads_v2.aggregate([
  {$group: {_id: {cid: "$campaign_id", ws: "$workflow_status"}, count: {$sum: 1}}},
  {$sort: {"_id.cid": 1, "_id.ws": 1}}
]).forEach(r => {
  var camp = db.outreach_campaigns_v2.findOne({campaign_id: r._id.cid}, {name: 1});
  print("  " + (camp ? camp.name : r._id.cid) + " | " + r._id.ws + " | " + r.count);
});

// Latest 5 sends
print("\nLatest 5 sends:");
db.outreach_sends_v2.find({}).sort({sent_at: -1}).limit(5).forEach(d => {
  print("  " + d.sent_at.toISOString() + " | " + d.email + " | from: " + d.from_email + " | status: " + (d.status || "sent"));
});

// ========== 2. BOUNCE STATUS ==========
print("\n=== BOUNCE STATUS ===");

// Check outreach_sends_v2 for bounced
var bouncedSends = db.outreach_sends_v2.countDocuments({status: "bounced"});
print("Sends marked bounced: " + bouncedSends);

// Check outreach_leads_v2 for bounced
var bouncedLeads = db.outreach_leads_v2.countDocuments({workflow_status: "bounced"});
print("Leads marked bounced: " + bouncedLeads);

// Check email_metadata in torpedo_gmail for bounces
var gmailDb = db.getSiblingDB("torpedo_gmail");
var bounceMeta = gmailDb.email_metadata.countDocuments({$or: [{classification: "bounce"}, {is_bounce: true}, {label: /bounce/i}]});
print("Gmail metadata bounce records: " + bounceMeta);

// Check for bounce-related fields in sends
var sendsWithBounce = db.outreach_sends_v2.countDocuments({$or: [{bounced: true}, {bounce_detected: true}, {status: "bounced"}]});
print("Sends with any bounce flag: " + sendsWithBounce);

// Check if there's a dedicated bounces collection
var collections = db.getCollectionNames();
var bounceColls = collections.filter(c => c.match(/bounce/i));
print("Bounce-related collections: " + (bounceColls.length > 0 ? bounceColls.join(", ") : "none"));

// Check email_classification DB
var classDb = db.getSiblingDB("email_automation");
var classColls = classDb.getCollectionNames();
print("email_automation collections: " + classColls.join(", "));

// ========== 3. ACTIVITY TRACKING ==========
print("\n=== ACTIVITY TRACKING ===");

// Check for open tracking
var opensInSends = db.outreach_sends_v2.countDocuments({$or: [{opened: true}, {open_count: {$gt: 0}}, {status: "opened"}]});
print("Sends with open tracking: " + opensInSends);

// Check for reply tracking
var repliesInSends = db.outreach_sends_v2.countDocuments({$or: [{replied: true}, {reply_detected: true}, {status: "replied"}]});
print("Sends with reply tracking: " + repliesInSends);

// Check for click tracking
var clicksInSends = db.outreach_sends_v2.countDocuments({$or: [{clicked: true}, {click_count: {$gt: 0}}, {status: "clicked"}]});
print("Sends with click tracking: " + clicksInSends);

// Check lead-level activity
var leadsWithActivity = db.outreach_leads_v2.countDocuments({$or: [
  {workflow_status: "replied"},
  {workflow_status: "opened"},
  {workflow_status: "bounced"},
  {workflow_status: "completed"},
  {last_reply_at: {$exists: true}},
  {last_open_at: {$exists: true}}
]});
print("Leads with any activity: " + leadsWithActivity);

// Check email_metadata for replies/opens
var gmailReplies = gmailDb.email_metadata.countDocuments({$or: [{classification: "reply"}, {is_reply: true}]});
print("Gmail metadata replies: " + gmailReplies);

// Check gmail for any inbound emails (recent)
var recentInbound = gmailDb.email_metadata.countDocuments({
  direction: "inbound",
  received_at: {$gte: new Date(Date.now() - 24*60*60*1000)}
});
print("Inbound emails (last 24h): " + recentInbound);

// Check for email classification results
print("\nEmail classification collections:");
classColls.forEach(c => {
  var count = classDb.getCollection(c).countDocuments({});
  print("  " + c + ": " + count + " docs");
});

// Sample a send record to see its schema
print("\n=== SAMPLE SEND RECORD SCHEMA ===");
var sampleSend = db.outreach_sends_v2.findOne({});
if (sampleSend) {
  print("Fields: " + Object.keys(sampleSend).join(", "));
  printjson(sampleSend);
}

// Sample a lead record to see activity fields
print("\n=== SAMPLE LEAD RECORD (in_sequence) ===");
var sampleLead = db.outreach_leads_v2.findOne({workflow_status: "in_sequence"});
if (sampleLead) {
  print("Fields: " + Object.keys(sampleLead).join(", "));
  printjson(sampleLead);
} else {
  print("No in_sequence leads found. Checking pending_scheduled...");
  sampleLead = db.outreach_leads_v2.findOne({workflow_status: "pending_scheduled"});
  if (sampleLead) {
    print("Fields: " + Object.keys(sampleLead).join(", "));
    printjson(sampleLead);
  }
}
