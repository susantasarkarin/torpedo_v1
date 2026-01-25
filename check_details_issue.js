// Check issue #3: Classified leads with no details
print("=== INVESTIGATING CLASSIFIED LEADS WITH NO DETAILS ===");
print("Current time:", new Date().toISOString());
print("");

// First check if leads have email addresses
print("=== EMAIL ADDRESS AVAILABILITY ===");
print("Total leads_enriched:", db.leads_enriched.countDocuments({}));
print("With email (not null):", db.leads_enriched.countDocuments({email: {$ne: null}}));
print("With email (non-empty string):", db.leads_enriched.countDocuments({email: {$exists: true, $ne: null, $ne: ""}}));
print("Without email:", db.leads_enriched.countDocuments({$or: [{email: null}, {email: ""}, {email: {$exists: false}}]}));

// Sample leads without email
print("\n=== SAMPLE LEADS WITHOUT EMAIL ===");
db.leads_enriched.find({$or: [{email: null}, {email: ""}]}).limit(3).forEach(function(l) {
  print("  ID:", l._id.toString());
  print("  Name:", l.name || l.first_name);
  print("  Email:", l.email);
  print("  Company:", l.company_name);
  print("  Source:", l.source);
  print("");
});

// Sample leads with email
print("\n=== SAMPLE LEADS WITH EMAIL ===");
db.leads_enriched.find({email: {$exists: true, $ne: null, $ne: ""}}).limit(3).forEach(function(l) {
  print("  ID:", l._id.toString());
  print("  Name:", l.name || l.first_name);
  print("  Email:", l.email);
  print("  Company:", l.company_name);
  print("");
});

// Check if those emails exist in email_metadata (torpedo_gmail)
print("\n=== CHECKING EMAIL METADATA CROSS-REFERENCE ===");
var sampleWithEmail = db.leads_enriched.findOne({email: {$exists: true, $ne: null, $ne: ""}});
if (sampleWithEmail && sampleWithEmail.email) {
  print("Looking for emails from:", sampleWithEmail.email);
  
  var torpedoDb = db.getSiblingDB("torpedo_gmail");
  var emailCount = torpedoDb.email_metadata.countDocuments({
    $or: [
      {from_email: {$regex: sampleWithEmail.email, $options: "i"}},
      {to_emails: {$regex: sampleWithEmail.email, $options: "i"}}
    ]
  });
  print("Emails found in torpedo_gmail.email_metadata:", emailCount);
}

// Check leads with gmail source - these should definitely have emails
print("\n=== GMAIL-SOURCED LEADS ===");
var gmailLeads = db.leads_enriched.find({source: "gmail"}).limit(5).toArray();
print("Gmail leads found:", gmailLeads.length);
gmailLeads.forEach(function(l) {
  print("  ID:", l._id.toString());
  print("  Name:", l.name || l.first_name);
  print("  Email:", l.email);
  print("  All fields:", Object.keys(l).slice(0, 20).join(", "));
  print("");
});

// Check database connection configuration
print("\n=== CHECKING LEAD SOURCES ===");
db.leads_enriched.aggregate([
  {$group: {_id: "$source", count: {$sum: 1}, hasEmail: {$sum: {$cond: [{$and: [{$ne: ["$email", null]}, {$ne: ["$email", ""]}]}, 1, 0]}}}},
  {$sort: {count: -1}}
]).forEach(function(r) {
  print("  " + r._id + ": " + r.count + " total, " + r.hasEmail + " with email");
});
