// Check system status for past 4 hours
var fourHoursAgo = new Date(Date.now() - 4*60*60*1000);

print("=== SYSTEM STATUS CHECK ===");
print("Current time:", new Date().toISOString());
print("Checking since:", fourHoursAgo.toISOString());
print("");

// 1. Email Classification Status
print("=== 1. EMAIL CLASSIFICATION STATUS ===");
var classifiedEmails = db.emails.find({classified_at: {$gte: fourHoursAgo}}).count();
print("Emails classified in past 4 hours:", classifiedEmails);

var emailsWithSummary = db.emails.find({
  classified_at: {$gte: fourHoursAgo},
  summary: {$exists: true, $ne: ""}
}).count();
print("Emails with summaries:", emailsWithSummary);

print("\nRecent classified emails (last 5):");
db.emails.find({classified_at: {$gte: fourHoursAgo}}).sort({classified_at: -1}).limit(5).forEach(function(e) {
  print("  Subject:", (e.subject || "N/A").substring(0,60));
  print("  Classified at:", e.classified_at);
  print("  Has Summary:", e.summary ? "Yes (" + e.summary.length + " chars)" : "No");
  print("  Classification:", e.classification || "N/A");
  print("");
});

// 2. Leads Generated from Mailbox
print("\n=== 2. LEADS GENERATED FROM MAILBOX (Past 4h) ===");
var leadsFromEmail = db.leads.find({
  createdAt: {$gte: fourHoursAgo},
  source: {$regex: /email|gmail|mailbox/i}
}).count();
print("Leads from email sources:", leadsFromEmail);

var allLeads4h = db.leads.find({createdAt: {$gte: fourHoursAgo}}).count();
print("All leads created in past 4h:", allLeads4h);

print("\nRecent leads (last 5):");
db.leads.find({createdAt: {$gte: fourHoursAgo}}).sort({createdAt: -1}).limit(5).forEach(function(l) {
  print("  Name:", l.firstName, l.lastName || "");
  print("  Email:", l.email || "N/A");
  print("  Source:", l.source || "N/A");
  print("  Created:", l.createdAt);
  print("");
});

// 3. Classified leads with no details
print("\n=== 3. CLASSIFIED LEADS WITH MISSING DETAILS ===");
var classifiedNoDetails = db.leads.find({
  $or: [
    {ai_classification_status: "classified"},
    {classificationStatus: "classified"},
    {status: "classified"}
  ],
  $or: [
    {ai_classification_details: {$exists: false}},
    {ai_classification_details: null},
    {ai_classification_details: ""},
    {classification_details: {$exists: false}},
    {classification_details: null}
  ]
}).count();
print("Classified leads with no details:", classifiedNoDetails);

// Sample of such leads
print("\nSample of classified leads without details (last 10):");
db.leads.find({
  $or: [
    {ai_classification_status: "classified"},
    {classificationStatus: "classified"}
  ]
}).sort({_id: -1}).limit(10).forEach(function(l) {
  print("  ID:", l._id);
  print("  Name:", l.firstName, l.lastName || "");
  print("  AI Status:", l.ai_classification_status || l.classificationStatus || "N/A");
  print("  Has ai_classification_details:", l.ai_classification_details ? "Yes" : "No");
  print("  Has classification_details:", l.classification_details ? "Yes" : "No");
  print("  Has aiAnalysis:", l.aiAnalysis ? "Yes" : "No");
  print("");
});

// Check field structure of a classified lead
print("\n=== FIELD STRUCTURE OF CLASSIFIED LEAD ===");
var sampleLead = db.leads.findOne({
  $or: [
    {ai_classification_status: "classified"},
    {classificationStatus: "classified"}
  ]
});
if (sampleLead) {
  print("Sample lead fields:", Object.keys(sampleLead).join(", "));
}

// Check AI classification collection if exists
print("\n=== AI CLASSIFICATIONS COLLECTION ===");
var aiClassCount = db.ai_classifications ? db.ai_classifications.count() : 0;
print("Total AI classifications:", aiClassCount);
var recentAI = db.ai_classifications ? db.ai_classifications.find({createdAt: {$gte: fourHoursAgo}}).count() : 0;
print("AI classifications in past 4h:", recentAI);
