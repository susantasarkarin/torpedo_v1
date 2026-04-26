// Check send schema
print("=== SEND RECORD FIELDS ===");
var s = db.outreach_sends_v2.findOne({});
if (s) print(Object.keys(s).join(", "));

// Check recent logs for any errors
print("\n=== RECENT OUTREACH ERRORS IN LOGS ===");
// Will do this via grep instead

// Check gmail_workspace for indira's mailbox
var gdb = db.getSiblingDB("torpedo_gmail");
print("\n=== GMAIL MAILBOXES ===");
gdb.workspace_mailboxes.find({},{email:1,display_name:1}).forEach(m => print("  " + m.email));

// Check recent email_metadata for indira (both sent & inbound)
print("\n=== RECENT EMAIL METADATA FOR INDIRA (last 24h) ===");
var oneDayAgo = new Date(Date.now() - 24*60*60*1000);
var meta = gdb.email_metadata.find({
  $or: [{from_email: "indira@surveyfieldwork.com"}, {to_email: "indira@surveyfieldwork.com"}],
  created_at: {$gte: oneDayAgo}
}).sort({created_at: -1}).limit(10);
meta.forEach(m => {
  print("  " + (m.created_at||m.received_at||"?").toISOString() + " | " + m.direction + " | from:" + m.from_email + " | to:" + (m.to_email||"?") + " | subj:" + (m.subject||"").substring(0,50));
});

print("\nTotal indira metadata (24h): " + gdb.email_metadata.countDocuments({
  $or: [{from_email: "indira@surveyfieldwork.com"}, {to_email: "indira@surveyfieldwork.com"}],
  created_at: {$gte: oneDayAgo}
}));
