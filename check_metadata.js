// Check email_metadata and campaign_platform
print("=== CHECKING email_metadata IN torpedo_gmail ===");
print("Current time:", new Date().toISOString());

var fourHoursAgo = new Date(Date.now() - 4*60*60*1000);
print("Checking since:", fourHoursAgo.toISOString());
print("");

// Check email_metadata structure
print("=== EMAIL_METADATA STRUCTURE ===");
var sampleEmail = db.email_metadata.findOne({});
if (sampleEmail) {
  print("Sample email fields:", Object.keys(sampleEmail).join(", "));
  print("\nSample data:");
  print("  Subject:", (sampleEmail.subject || "N/A").substring(0, 60));
  print("  From:", sampleEmail.from || sampleEmail.sender || "N/A");
  print("  Date:", sampleEmail.date || sampleEmail.receivedDate || sampleEmail.received_at);
  print("  Has classification:", sampleEmail.classification ? "Yes" : "No");
  print("  Has summary:", sampleEmail.summary ? "Yes" : "No");
  print("  Has ai_summary:", sampleEmail.ai_summary ? "Yes" : "No");
  print("  Classified:", sampleEmail.classified_at || sampleEmail.classification_date || "N/A");
}

// Check recent emails in metadata
print("\n=== EMAIL_METADATA - RECENT ACTIVITY ===");

// Find date field name
var emailWithDate = db.email_metadata.findOne({$or: [
  {date: {$exists: true}},
  {receivedDate: {$exists: true}},
  {received_at: {$exists: true}},
  {internalDate: {$exists: true}}
]});

if (emailWithDate) {
  print("Date field found:", emailWithDate.date ? "date" : 
    emailWithDate.receivedDate ? "receivedDate" : 
    emailWithDate.received_at ? "received_at" : 
    emailWithDate.internalDate ? "internalDate" : "unknown");
}

// Last 5 emails sorted by various date fields
print("\nLast 5 emails by internalDate:");
db.email_metadata.find({}).sort({internalDate: -1}).limit(5).forEach(function(e) {
  print("  Subject:", (e.subject || "N/A").substring(0, 50));
  print("  From:", (e.from || e.sender || "N/A").substring(0, 40));
  print("  internalDate:", e.internalDate);
  print("  Has classification:", e.classification ? "Yes" : "No");
  print("  Has summary:", (e.summary || e.ai_summary) ? "Yes" : "No");
  print("  classified_at:", e.classified_at || "N/A");
  print("");
});

// Check classifications in past 4 hours
print("\n=== CLASSIFICATIONS IN PAST 4 HOURS ===");
var recentClassified = db.email_metadata.countDocuments({
  classified_at: {$gte: fourHoursAgo}
});
print("Emails classified in past 4h:", recentClassified);

var recentWithSummary = db.email_metadata.countDocuments({
  $and: [
    {classified_at: {$gte: fourHoursAgo}},
    {$or: [{summary: {$exists: true, $ne: ""}}, {ai_summary: {$exists: true, $ne: ""}}]}
  ]
});
print("With summaries in past 4h:", recentWithSummary);

// Total classified
print("\n=== OVERALL CLASSIFICATION STATUS ===");
print("Total with classified_at:", db.email_metadata.countDocuments({classified_at: {$exists: true}}));
print("Total with summary:", db.email_metadata.countDocuments({summary: {$exists: true, $ne: ""}}));
print("Total with ai_summary:", db.email_metadata.countDocuments({ai_summary: {$exists: true, $ne: ""}}));
print("Total with classification:", db.email_metadata.countDocuments({classification: {$exists: true}}));

// Last classified email
print("\n=== LAST CLASSIFIED EMAIL ===");
var lastClassified = db.email_metadata.findOne(
  {classified_at: {$exists: true}}, 
  {}, 
  {sort: {classified_at: -1}}
);
if (lastClassified) {
  print("Subject:", lastClassified.subject);
  print("Classified at:", lastClassified.classified_at);
  print("Classification:", lastClassified.classification);
  print("Summary:", (lastClassified.summary || lastClassified.ai_summary || "N/A").substring(0, 200));
} else {
  print("No classified emails found!");
}
