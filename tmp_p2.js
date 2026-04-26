// Part 2 - Bounces
print("=== BOUNCES ===");
print("Sends status=bounced: " + db.outreach_sends_v2.countDocuments({status:"bounced"}));
print("Sends bounced=true: " + db.outreach_sends_v2.countDocuments({bounced:true}));
print("Leads workflow=bounced: " + db.outreach_leads_v2.countDocuments({workflow_status:"bounced"}));

var gmailDb = db.getSiblingDB("torpedo_gmail");
print("Gmail bounce classification: " + gmailDb.email_metadata.countDocuments({classification:"bounce"}));
print("Gmail bounce label: " + gmailDb.email_metadata.countDocuments({labels:{$regex:/bounce/i}}));

// Check if any DSN/bounce emails exist in metadata
print("Gmail mailer-daemon: " + gmailDb.email_metadata.countDocuments({from_email:{$regex:/mailer-daemon|postmaster/i}}));

// Check bounce collections
print("\nCollections with 'bounce':");
db.getCollectionNames().filter(c => /bounce/i.test(c)).forEach(c => print("  " + c));

// Distinct send statuses
print("\nDistinct send statuses: " + JSON.stringify(db.outreach_sends_v2.distinct("status")));
