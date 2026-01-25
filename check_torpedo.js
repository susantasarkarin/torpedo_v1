// Check torpedo_gmail database (main database)
print("=== CHECKING torpedo_gmail DATABASE ===");
print("Current time:", new Date().toISOString());
print("");

var fourHoursAgo = new Date(Date.now() - 4*60*60*1000);
print("Checking since:", fourHoursAgo.toISOString());

// List collections
print("\n=== COLLECTIONS ===");
db.getCollectionNames().forEach(function(c) {
  var count = db[c].countDocuments({});
  print(c + ":", count);
});

// Check emails
print("\n=== EMAILS ===");
print("Total emails:", db.emails.countDocuments({}));
print("Emails in past 4h:", db.emails.countDocuments({receivedDate: {$gte: fourHoursAgo}}));
print("Emails classified in past 4h:", db.emails.countDocuments({classified_at: {$gte: fourHoursAgo}}));
print("Emails with summary:", db.emails.countDocuments({summary: {$exists: true, $ne: ""}}));

// Last emails
print("\nLast 3 emails:");
db.emails.find({}).sort({receivedDate: -1}).limit(3).forEach(function(e) {
  print("  Subject:", (e.subject || "N/A").substring(0,50));
  print("  From:", e.from || "N/A");
  print("  Received:", e.receivedDate);
  print("  Classified:", e.classified_at || "Not classified");
  print("  Has summary:", e.summary ? "Yes" : "No");
  print("");
});

// Check leads
print("\n=== LEADS ===");
print("Total leads:", db.leads.countDocuments({}));
print("Leads in past 4h:", db.leads.countDocuments({createdAt: {$gte: fourHoursAgo}}));

// Lead status breakdown
print("\nLeads by ai_classification_status:");
db.leads.aggregate([
  {$group: {_id: "$ai_classification_status", count: {$sum: 1}}},
  {$sort: {count: -1}}
]).forEach(function(r) {
  print("  ", r._id || "(null)", ":", r.count);
});

// Last leads
print("\nLast 3 leads:");
db.leads.find({}).sort({createdAt: -1}).limit(3).forEach(function(l) {
  print("  ID:", l._id.toString());
  print("  Name:", l.firstName, l.lastName || "");
  print("  Email:", l.email);
  print("  Created:", l.createdAt);
  print("  AI Status:", l.ai_classification_status);
  print("  Source:", l.source);
  print("");
});

// Check leads marked as classified but missing details
print("\n=== CLASSIFIED LEADS ANALYSIS ===");
var classifiedCount = db.leads.countDocuments({ai_classification_status: "classified"});
print("Leads with ai_classification_status = 'classified':", classifiedCount);

var withDetails = db.leads.countDocuments({
  ai_classification_status: "classified",
  aiAnalysis: {$exists: true, $ne: null}
});
print("With aiAnalysis:", withDetails);

var withoutDetails = db.leads.countDocuments({
  ai_classification_status: "classified",
  $or: [
    {aiAnalysis: {$exists: false}},
    {aiAnalysis: null}
  ]
});
print("Without aiAnalysis:", withoutDetails);

// Sample of classified leads without details
print("\nSample classified leads without aiAnalysis (last 5):");
db.leads.find({
  ai_classification_status: "classified",
  $or: [
    {aiAnalysis: {$exists: false}},
    {aiAnalysis: null}
  ]
}).sort({createdAt: -1}).limit(5).forEach(function(l) {
  print("  ID:", l._id.toString());
  print("  Name:", l.firstName, l.lastName || "");
  print("  Email:", l.email);
  print("  Source:", l.source);
  print("  Created:", l.createdAt);
  print("  Fields:", Object.keys(l).join(", "));
  print("");
});

// Check a classified lead with details to see what fields should exist
print("\n=== SAMPLE CLASSIFIED LEAD WITH DETAILS ===");
var goodLead = db.leads.findOne({
  ai_classification_status: "classified",
  aiAnalysis: {$exists: true, $ne: null}
});
if (goodLead) {
  print("ID:", goodLead._id.toString());
  print("Name:", goodLead.firstName, goodLead.lastName || "");
  print("aiAnalysis keys:", Object.keys(goodLead.aiAnalysis || {}).join(", "));
  print("Full aiAnalysis:", JSON.stringify(goodLead.aiAnalysis).substring(0, 500));
} else {
  print("No classified lead with aiAnalysis found!");
}
