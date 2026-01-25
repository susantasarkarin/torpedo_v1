// Deep dive into leads_enriched fields
print("=== LEADS_ENRICHED FIELD ANALYSIS ===");
print("Current time:", new Date().toISOString());
print("");

// Check all unique values of status-like fields
print("=== STATUS FIELD VALUES ===");

["classification_status", "status", "ai_status", "processing_status", "enrichment_status"].forEach(function(field) {
  print("\n" + field + ":");
  db.leads_enriched.aggregate([
    {$group: {_id: "$" + field, count: {$sum: 1}}},
    {$sort: {count: -1}},
    {$limit: 10}
  ]).forEach(function(r) {
    print("  " + JSON.stringify(r._id) + ": " + r.count);
  });
});

// Check for any field containing "classif" or "status"
print("\n=== ALL FIELDS ON A SAMPLE LEAD ===");
var sample = db.leads_enriched.findOne({});
if (sample) {
  var fields = Object.keys(sample);
  fields.forEach(function(f) {
    var val = sample[f];
    var valStr = "";
    if (val === null) valStr = "null";
    else if (val === undefined) valStr = "undefined";
    else if (typeof val === "object") valStr = JSON.stringify(val).substring(0, 100);
    else valStr = String(val).substring(0, 100);
    print("  " + f + " (" + typeof val + "): " + valStr);
  });
}

// Check if any leads have been marked as classified or enriched in any way
print("\n=== LEADS WITH ANY ENRICHMENT ===");
var enriched = db.leads_enriched.countDocuments({
  $or: [
    {ai_summary: {$exists: true, $ne: null, $ne: ""}},
    {email_summary: {$exists: true, $ne: null, $ne: ""}},
    {enriched: true},
    {is_enriched: true},
    {classification_status: "classified"},
    {status: "classified"},
    {status: "enriched"}
  ]
});
print("Leads with any enrichment:", enriched);

// Check leads collection as well
print("\n=== LEGACY LEADS COLLECTION ===");
print("Total:", db.leads.countDocuments({}));
var leadSample = db.leads.findOne({});
if (leadSample) {
  print("Sample fields:", Object.keys(leadSample).join(", "));
  print("classification_status:", leadSample.classification_status);
  print("status:", leadSample.status);
}

// Check lead_ai_classification_logs
print("\n=== AI CLASSIFICATION LOGS ===");
print("Total logs:", db.lead_ai_classification_logs.countDocuments({}));
var recentLog = db.lead_ai_classification_logs.findOne({}, {}, {sort: {created_at: -1}});
if (recentLog) {
  print("Last log:", recentLog.created_at);
  print("Status:", recentLog.status);
  print("Lead ID:", recentLog.lead_id);
}

// Check what the UI might be querying
print("\n=== CHECKING UI-RELEVANT QUERIES ===");
// The UI might be checking for classification_status === "classified" OR 
// looking at a different field

// Count by source
print("\nLeads by source:");
db.leads_enriched.aggregate([
  {$group: {_id: "$source", count: {$sum: 1}}},
  {$sort: {count: -1}},
  {$limit: 10}
]).forEach(function(r) {
  print("  " + (r._id || "(null)") + ": " + r.count);
});
