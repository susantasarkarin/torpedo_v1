var gdb = db.getSiblingDB("torpedo_gmail");
var mid = "696b01805cad63fe3d9c4316";
var twoHoursAgo = new Date(Date.now() - 2*60*60*1000);

// Count bounces (recent)
var bounces = gdb.email_metadata.countDocuments({
  mailbox_id: mid, 
  synced_at: {$gte: twoHoursAgo},
  $or: [
    {from_email: {$regex: /mailer-daemon|postmaster/i}},
    {subject: {$regex: /undeliverable|delivery.*fail|returned.*mail/i}}
  ]
});
print("Bounce emails (last 2h): " + bounces);

// Count all inbound (recent)
var inbound = gdb.email_metadata.countDocuments({
  mailbox_id: mid,
  synced_at: {$gte: twoHoursAgo},
  direction: "inbound"
});
print("All inbound (last 2h): " + inbound);

// Non-bounce inbound (potential replies)
var replies = gdb.email_metadata.countDocuments({
  mailbox_id: mid,
  synced_at: {$gte: twoHoursAgo},
  direction: "inbound",
  from_email: {$not: /mailer-daemon|postmaster/i},
  subject: {$not: /undeliverable|delivery.*fail|returned.*mail/i}
});
print("Non-bounce inbound (last 2h): " + replies);

// Show non-bounce inbound
if (replies > 0) {
  print("\nPotential replies:");
  gdb.email_metadata.find({
    mailbox_id: mid,
    synced_at: {$gte: twoHoursAgo},
    direction: "inbound",
    from_email: {$not: /mailer-daemon|postmaster/i},
    subject: {$not: /undeliverable|delivery.*fail|returned.*mail/i}
  }).sort({synced_at: -1}).limit(10).forEach(m => {
    print("  " + m.synced_at.toISOString() + " | from: " + m.from_email + " | subj: " + (m.subject||"").substring(0,60));
  });
}

// Show sample bounce details
print("\nSample bounce emails:");
gdb.email_metadata.find({
  mailbox_id: mid,
  synced_at: {$gte: twoHoursAgo},
  $or: [
    {from_email: {$regex: /mailer-daemon|postmaster/i}},
    {subject: {$regex: /undeliverable|delivery.*fail/i}}
  ]
}).sort({synced_at: -1}).limit(5).forEach(m => {
  print("  " + m.synced_at.toISOString() + " | from: " + m.from_email + " | subj: " + (m.subject||"").substring(0,70));
});

// Count outbound (sent emails synced back)
var outbound = gdb.email_metadata.countDocuments({
  mailbox_id: mid,
  synced_at: {$gte: twoHoursAgo},
  direction: "outbound"
});
print("\nOutbound synced (last 2h): " + outbound);

// Now check: are bounces being linked to outreach?
print("\n=== OUTREACH BOUNCE LINK CHECK ===");
var db2 = db.getSiblingDB("torpedo");
print("Outreach sends with bounced status: " + db2.outreach_sends_v2.countDocuments({status: "bounced"}));
print("Outreach leads with bounced status: " + db2.outreach_leads_v2.countDocuments({workflow_status: "bounced"}));
print("Bounce suppression list: " + db2.outreach_bounce_suppression.countDocuments({}));
