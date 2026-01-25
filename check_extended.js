// Extended check - look at all data
print("=== EXTENDED SYSTEM CHECK ===");
print("Current time:", new Date().toISOString());
print("");

// Check total emails
print("=== EMAILS OVERVIEW ===");
print("Total emails:", db.emails.countDocuments({}));
print("Emails with classification:", db.emails.countDocuments({classification: {$exists: true}}));
print("Emails with summary:", db.emails.countDocuments({summary: {$exists: true, $ne: ""}}));
print("Emails with classified_at:", db.emails.countDocuments({classified_at: {$exists: true}}));

// Last classified email
print("\nLast classified email:");
var lastEmail = db.emails.findOne({classified_at: {$exists: true}}, {}, {sort: {classified_at: -1}});
if (lastEmail) {
  print("  Subject:", (lastEmail.subject || "N/A").substring(0,60));
  print("  Classified at:", lastEmail.classified_at);
  print("  Classification:", lastEmail.classification);
}

// Check leads
print("\n=== LEADS OVERVIEW ===");
print("Total leads:", db.leads.countDocuments({}));

// Check by status
print("\nLeads by AI classification status:");
db.leads.aggregate([
  {$group: {_id: "$ai_classification_status", count: {$sum: 1}}}
]).forEach(function(r) {
  print("  ", r._id || "null/undefined", ":", r.count);
});

print("\nLeads by classificationStatus:");
db.leads.aggregate([
  {$group: {_id: "$classificationStatus", count: {$sum: 1}}}
]).forEach(function(r) {
  print("  ", r._id || "null/undefined", ":", r.count);
});

// Last lead created
print("\nLast 3 leads created:");
db.leads.find({}).sort({createdAt: -1}).limit(3).forEach(function(l) {
  print("  Name:", l.firstName, l.lastName || "");
  print("  Email:", l.email || "N/A");
  print("  Source:", l.source || "N/A");
  print("  Created:", l.createdAt);
  print("  AI Status:", l.ai_classification_status || "N/A");
  print("  classificationStatus:", l.classificationStatus || "N/A");
  print("");
});

// Check for "AI database" collection - might be different name
print("\n=== CHECKING ALL COLLECTIONS ===");
db.getCollectionNames().forEach(function(c) {
  var count = db[c].countDocuments({});
  print(c + ":", count);
});

// Check leads with "classified" status but missing details
print("\n=== LEADS MARKED CLASSIFIED ===");
var classifiedLeads = db.leads.find({
  $or: [
    {ai_classification_status: "classified"},
    {classificationStatus: "classified"},
    {ai_classification_status: "success"},
    {classificationStatus: "success"}
  ]
}).limit(5);

classifiedLeads.forEach(function(l) {
  print("  ID:", l._id.toString());
  print("  Name:", l.firstName, l.lastName || "");
  print("  ai_classification_status:", l.ai_classification_status);
  print("  classificationStatus:", l.classificationStatus);
  print("  ai_classification_details exists:", l.ai_classification_details ? "Yes" : "No");
  print("  aiAnalysis exists:", l.aiAnalysis ? "Yes" : "No");
  if (l.aiAnalysis) {
    print("  aiAnalysis keys:", Object.keys(l.aiAnalysis).join(", "));
  }
  print("  classification exists:", l.classification ? "Yes" : "No");
  print("");
});

// Check lead sources
print("\n=== LEAD SOURCES ===");
db.leads.aggregate([
  {$group: {_id: "$source", count: {$sum: 1}}},
  {$sort: {count: -1}},
  {$limit: 10}
]).forEach(function(r) {
  print("  ", r._id || "null", ":", r.count);
});

// Last 24 hours activity
print("\n=== LAST 24 HOURS ACTIVITY ===");
var twentyFourHoursAgo = new Date(Date.now() - 24*60*60*1000);
print("Emails classified:", db.emails.countDocuments({classified_at: {$gte: twentyFourHoursAgo}}));
print("Leads created:", db.leads.countDocuments({createdAt: {$gte: twentyFourHoursAgo}}));
