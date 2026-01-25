// Check email_automation leads_enriched (AI Database)
print("=== EMAIL_AUTOMATION LEADS_ENRICHED (AI DATABASE) ===");
print("Current time:", new Date().toISOString());
print("");

var fourHoursAgo = new Date(Date.now() - 4*60*60*1000);

// Stats
print("Total leads_enriched:", db.leads_enriched.countDocuments({}));
print("Recent (4h):", db.leads_enriched.countDocuments({created_at: {$gte: fourHoursAgo}}));

// By classification_status
print("\n=== BY CLASSIFICATION STATUS ===");
db.leads_enriched.aggregate([
  {$group: {_id: "$classification_status", count: {$sum: 1}}},
  {$sort: {count: -1}}
]).forEach(function(r) {
  print("  " + (r._id || "(null)") + ": " + r.count);
});

// Check what fields exist on classified leads
print("\n=== FIELD ANALYSIS ON CLASSIFIED LEADS ===");
var classifiedCount = db.leads_enriched.countDocuments({classification_status: "classified"});
print("Total classified:", classifiedCount);

// Check for detail fields
var withSummary = db.leads_enriched.countDocuments({
  classification_status: "classified",
  ai_summary: {$exists: true, $ne: null, $ne: ""}
});
print("With ai_summary:", withSummary);

var withEmailSummary = db.leads_enriched.countDocuments({
  classification_status: "classified",
  email_summary: {$exists: true, $ne: null, $ne: ""}
});
print("With email_summary:", withEmailSummary);

var withAnalysis = db.leads_enriched.countDocuments({
  classification_status: "classified",
  analysis: {$exists: true, $ne: null}
});
print("With analysis:", withAnalysis);

var withDetails = db.leads_enriched.countDocuments({
  classification_status: "classified",
  details: {$exists: true, $ne: null}
});
print("With details:", withDetails);

var withEmails = db.leads_enriched.countDocuments({
  classification_status: "classified",
  emails: {$exists: true, $ne: [], $ne: null}
});
print("With emails array:", withEmails);

// Sample classified lead to see all fields
print("\n=== SAMPLE CLASSIFIED LEAD (with ai_summary) ===");
var goodLead = db.leads_enriched.findOne({
  classification_status: "classified",
  ai_summary: {$exists: true, $ne: null, $ne: ""}
});
if (goodLead) {
  print("ID:", goodLead._id.toString());
  print("Name:", goodLead.name || goodLead.firstName);
  print("Email:", goodLead.email);
  print("Company:", goodLead.company);
  print("classification_status:", goodLead.classification_status);
  print("ai_summary:", (goodLead.ai_summary || "").substring(0, 200));
  print("All fields:", Object.keys(goodLead).join(", "));
} else {
  print("No classified lead with ai_summary found!");
}

// Sample classified lead WITHOUT details
print("\n=== SAMPLE CLASSIFIED LEAD (WITHOUT ai_summary) ===");
var badLead = db.leads_enriched.findOne({
  classification_status: "classified",
  $or: [
    {ai_summary: {$exists: false}},
    {ai_summary: null},
    {ai_summary: ""}
  ]
});
if (badLead) {
  print("ID:", badLead._id.toString());
  print("Name:", badLead.name || badLead.firstName);
  print("Email:", badLead.email);
  print("Company:", badLead.company);
  print("classification_status:", badLead.classification_status);
  print("ai_summary:", badLead.ai_summary);
  print("All fields:", Object.keys(badLead).join(", "));
  
  // Check what values those fields have
  print("\nField values:");
  ["ai_summary", "email_summary", "analysis", "details", "classification_result", "conversation_summary"].forEach(function(f) {
    var val = badLead[f];
    print("  " + f + ":", typeof val, val ? (typeof val === "string" ? val.substring(0, 50) : JSON.stringify(val).substring(0, 100)) : "(empty/null)");
  });
} else {
  print("All classified leads have ai_summary!");
}

// Count classified without details
print("\n=== CLASSIFIED LEADS MISSING DETAILS ===");
var missingDetails = db.leads_enriched.countDocuments({
  classification_status: "classified",
  $or: [
    {ai_summary: {$exists: false}},
    {ai_summary: null},
    {ai_summary: ""}
  ]
});
print("Classified without ai_summary:", missingDetails);

// Recent leads
print("\n=== LAST 5 LEADS CREATED ===");
db.leads_enriched.find({}).sort({created_at: -1}).limit(5).forEach(function(l) {
  print("  ID:", l._id.toString());
  print("  Name:", l.name || l.firstName || "N/A");
  print("  Email:", l.email);
  print("  Status:", l.classification_status);
  print("  Has ai_summary:", l.ai_summary ? "Yes" : "No");
  print("  Created:", l.created_at);
  print("");
});

// Check if classification is running
print("\n=== RECENT CLASSIFICATIONS ===");
var recentClassified = db.leads_enriched.countDocuments({
  classification_status: "classified",
  classified_at: {$gte: fourHoursAgo}
});
print("Classified in past 4h:", recentClassified);

var last = db.leads_enriched.findOne(
  {classified_at: {$exists: true}},
  {},
  {sort: {classified_at: -1}}
);
if (last) {
  print("Last classification:", last.classified_at);
}
