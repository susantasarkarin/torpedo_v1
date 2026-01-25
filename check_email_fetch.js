// Test email fetching for a lead
print("=== TESTING EMAIL FETCH FOR LEAD ===");
print("");

// Get a gmail-sourced lead with email
var lead = db.leads_enriched.findOne({source: "gmail", email: {$ne: null, $ne: ""}});
if (!lead) {
  print("No gmail lead with email found!");
} else {
  print("Lead ID:", lead._id.toString());
  print("Name:", lead.name || lead.first_name);
  print("Email:", lead.email);
  print("Company:", lead.company_name);
  print("");
  
  // Check torpedo_gmail for emails
  var torpedoDb = db.getSiblingDB("torpedo_gmail");
  
  // Count emails for this lead
  var emailQuery = {
    $or: [
      {from_email: {$regex: lead.email, $options: "i"}},
      {to_emails: {$regex: lead.email, $options: "i"}}
    ]
  };
  
  var emailCount = torpedoDb.email_metadata.countDocuments(emailQuery);
  print("Emails found for this lead:", emailCount);
  
  if (emailCount > 0) {
    print("\nSample emails:");
    torpedoDb.email_metadata.find(emailQuery).limit(3).forEach(function(e) {
      print("  Subject:", (e.subject || "N/A").substring(0, 50));
      print("  From:", e.from_email || "N/A");
      print("  To:", e.to_emails);
      print("  Has AI Summary:", e.ai_summary ? "Yes" : "No");
      print("  ai_category:", e.ai_category);
      print("");
    });
  }
}

// Also check a random gmail lead
print("\n=== CHECKING ANOTHER GMAIL LEAD ===");
var gmailLeads = db.leads_enriched.find({source: "gmail"}).limit(10).toArray();
var torpedoDb = db.getSiblingDB("torpedo_gmail");

gmailLeads.forEach(function(l) {
  if (!l.email) return;
  var count = torpedoDb.email_metadata.countDocuments({
    $or: [
      {from_email: {$regex: l.email, $options: "i"}},
      {to_emails: {$regex: l.email, $options: "i"}}
    ]
  });
  print("  " + l.email + ": " + count + " emails");
});
