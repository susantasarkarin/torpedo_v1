// Final comprehensive check
print("=== COMPREHENSIVE SYSTEM CHECK ===");
print("Current time:", new Date().toISOString());

var fourHoursAgo = new Date(Date.now() - 4*60*60*1000);
var twentyFourHoursAgo = new Date(Date.now() - 24*60*60*1000);
print("4 hours ago:", fourHoursAgo.toISOString());
print("");

// 1. EMAIL CLASSIFICATION using correct field ai_classified_at
print("=== 1. EMAIL CLASSIFICATION STATUS ===");
print("Total emails:", db.email_metadata.countDocuments({}));
print("Total with ai_summary:", db.email_metadata.countDocuments({ai_summary: {$exists: true, $ne: ""}}));
print("Total with ai_classified_at:", db.email_metadata.countDocuments({ai_classified_at: {$exists: true}}));

// Recent classifications
var recentAI = db.email_metadata.countDocuments({
  ai_classified_at: {$gte: fourHoursAgo}
});
print("\nClassified in past 4 hours:", recentAI);

var recent24h = db.email_metadata.countDocuments({
  ai_classified_at: {$gte: twentyFourHoursAgo}
});
print("Classified in past 24 hours:", recent24h);

// Last classification
print("\nLast classified email:");
var lastAI = db.email_metadata.findOne(
  {ai_classified_at: {$exists: true}},
  {},
  {sort: {ai_classified_at: -1}}
);
if (lastAI) {
  print("  Subject:", (lastAI.subject || "N/A").substring(0, 60));
  print("  From:", lastAI.from_email || lastAI.from_name || "N/A");
  print("  AI Classified at:", lastAI.ai_classified_at);
  print("  AI Category:", lastAI.ai_category);
  print("  AI Summary:", (lastAI.ai_summary || "N/A").substring(0, 150));
  print("  Is Sales Lead:", lastAI.ai_is_sales_lead);
} else {
  print("  No AI classified emails found!");
}

// 2. Check timestamp field instead
print("\n=== CHECKING BY TIMESTAMP ===");
var recentByTimestamp = db.email_metadata.countDocuments({
  timestamp: {$gte: fourHoursAgo}
});
print("Emails received in past 4h (by timestamp):", recentByTimestamp);

print("\nRecent emails by timestamp:");
db.email_metadata.find({}).sort({timestamp: -1}).limit(3).forEach(function(e) {
  print("  Subject:", (e.subject || "N/A").substring(0, 50));
  print("  Timestamp:", e.timestamp);
  print("  Has ai_summary:", e.ai_summary ? "Yes" : "No");
  print("  ai_classified_at:", e.ai_classified_at || "Not classified");
  print("");
});

// 3. Check if classification is happening
print("\n=== AI CLASSIFICATION DATES DISTRIBUTION ===");
db.email_metadata.aggregate([
  {$match: {ai_classified_at: {$exists: true}}},
  {$project: {day: {$dateToString: {format: "%Y-%m-%d", date: "$ai_classified_at"}}}},
  {$group: {_id: "$day", count: {$sum: 1}}},
  {$sort: {_id: -1}},
  {$limit: 10}
]).forEach(function(r) {
  print("  ", r._id, ":", r.count);
});

// 4. Check sales leads identified
print("\n=== SALES LEADS IDENTIFIED ===");
print("Total with ai_is_sales_lead=true:", db.email_metadata.countDocuments({ai_is_sales_lead: true}));
print("Total with ai_is_sales_lead=false:", db.email_metadata.countDocuments({ai_is_sales_lead: false}));

// Recent sales leads
print("\nRecent sales leads:");
db.email_metadata.find({ai_is_sales_lead: true}).sort({ai_classified_at: -1}).limit(3).forEach(function(e) {
  print("  Subject:", (e.subject || "N/A").substring(0, 50));
  print("  From:", e.from_email || "N/A");
  print("  ai_classified_at:", e.ai_classified_at);
  print("");
});
