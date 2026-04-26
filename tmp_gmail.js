var gdb = db.getSiblingDB("torpedo_gmail");

// Check using mailbox_id instead of email (faster with index)
var indiraBox = gdb.workspace_mailboxes.findOne({email: "indira@surveyfieldwork.com"});
print("Indira mailbox_id: " + (indiraBox ? indiraBox._id : "NOT FOUND"));

if (indiraBox) {
  var mid = indiraBox._id;
  var oneDayAgo = new Date(Date.now() - 2*60*60*1000); // last 2 hours
  
  // Count recent emails for this mailbox
  var total = gdb.email_metadata.countDocuments({mailbox_id: mid, created_at: {$gte: oneDayAgo}});
  print("Indira emails (last 2h): " + total);
  
  // Count by direction
  var outbound = gdb.email_metadata.countDocuments({mailbox_id: mid, direction: "outbound", created_at: {$gte: oneDayAgo}});
  var inbound = gdb.email_metadata.countDocuments({mailbox_id: mid, direction: "inbound", created_at: {$gte: oneDayAgo}});
  print("  Outbound: " + outbound);
  print("  Inbound: " + inbound);
  
  // Show inbound emails (potential replies/bounces)
  if (inbound > 0) {
    print("\nInbound emails to indira:");
    gdb.email_metadata.find({mailbox_id: mid, direction: "inbound", created_at: {$gte: oneDayAgo}})
      .sort({created_at: -1}).limit(10).forEach(m => {
        print("  " + (m.created_at||"?") + " | from: " + (m.from_email||"?") + " | subj: " + (m.subject||"").substring(0,60) + " | class: " + (m.classification||"none"));
    });
  }
  
  // Show sample outbound
  print("\nLatest 3 outbound:");
  gdb.email_metadata.find({mailbox_id: mid, direction: "outbound", created_at: {$gte: oneDayAgo}})
    .sort({created_at: -1}).limit(3).forEach(m => {
      print("  " + (m.created_at||"?") + " | to: " + (m.to_email||"?") + " | subj: " + (m.subject||"").substring(0,60));
  });
}
