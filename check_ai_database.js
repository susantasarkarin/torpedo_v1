// Check leads_enriched collection (AI Database)
print("=== AI DATABASE (leads_enriched) CHECK ===");
print("Current time:", new Date().toISOString());
print("");

var fourHoursAgo = new Date(Date.now() - 4*60*60*1000);

// Check in torpedo_gmail database
print("=== TORPEDO_GMAIL DATABASE ===");
var collections = db.getCollectionNames();
print("Collections:", collections.join(", "));

// Check leads_enriched
print("\n=== leads_enriched collection ===");
if (collections.indexOf("leads_enriched") >= 0) {
  print("Total records:", db.leads_enriched.countDocuments({}));
  print("Recent (4h):", db.leads_enriched.countDocuments({created_at: {$gte: fourHoursAgo}}));
  
  print("\nBy classification_status:");
  db.leads_enriched.aggregate([
    {$group: {_id: "$classification_status", count: {$sum: 1}}},
    {$sort: {count: -1}}
  ]).forEach(function(r) {
    print("  " + (r._id || "(null)") + ": " + r.count);
  });
  
  print("\nLast 5 leads:");
  db.leads_enriched.find({}).sort({created_at: -1}).limit(5).forEach(function(l) {
    print("  ID:", l._id.toString());
    print("  Name:", l.name || l.firstName || "N/A");
    print("  Email:", l.email || "N/A");
    print("  Company:", l.company || "N/A");
    print("  classification_status:", l.classification_status);
    print("  ai_summary exists:", l.ai_summary ? "Yes" : "No");
    print("  email_summary exists:", l.email_summary ? "Yes" : "No");
    print("  Created:", l.created_at);
    print("  Fields:", Object.keys(l).slice(0, 15).join(", "));
    print("");
  });
  
  // Sample classified lead with and without details
  print("\n=== CLASSIFIED LEADS ANALYSIS ===");
  var withDetails = db.leads_enriched.countDocuments({
    classification_status: "classified",
    $or: [
      {ai_summary: {$exists: true, $ne: ""}},
      {email_summary: {$exists: true, $ne: ""}},
      {details: {$exists: true}}
    ]
  });
  print("Classified with details:", withDetails);
  
  var withoutDetails = db.leads_enriched.countDocuments({
    classification_status: "classified",
    $and: [
      {$or: [{ai_summary: {$exists: false}}, {ai_summary: ""}]},
      {$or: [{email_summary: {$exists: false}}, {email_summary: ""}]},
      {$or: [{details: {$exists: false}}, {details: null}]}
    ]
  });
  print("Classified without details:", withoutDetails);
  
  // Sample of classified with details
  print("\n=== SAMPLE CLASSIFIED WITH DETAILS ===");
  var goodLead = db.leads_enriched.findOne({
    classification_status: "classified",
    ai_summary: {$exists: true, $ne: ""}
  });
  if (goodLead) {
    print("ID:", goodLead._id.toString());
    print("Name:", goodLead.name || goodLead.firstName);
    print("ai_summary:", (goodLead.ai_summary || "").substring(0, 200));
  } else {
    print("No classified lead with ai_summary found");
  }
  
  // Sample of classified without details  
  print("\n=== SAMPLE CLASSIFIED WITHOUT DETAILS ===");
  var badLead = db.leads_enriched.findOne({
    classification_status: "classified",
    ai_summary: {$in: [null, "", undefined]}
  });
  if (badLead) {
    print("ID:", badLead._id.toString());
    print("Name:", badLead.name || badLead.firstName);
    print("Email:", badLead.email);
    print("All fields:", Object.keys(badLead).join(", "));
  } else {
    print("All classified leads have details!");
  }
} else {
  print("leads_enriched collection not found!");
}

// Check email_metadata for sales leads that should become leads
print("\n=== SALES LEADS IN EMAIL_METADATA ===");
print("Total sales leads:", db.email_metadata.countDocuments({ai_is_sales_lead: true}));
print("Recent sales leads (4h):", db.email_metadata.countDocuments({
  ai_is_sales_lead: true,
  ai_classified_at: {$gte: fourHoursAgo}
}));
